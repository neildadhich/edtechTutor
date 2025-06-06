import os
from flask import Flask, request, jsonify, send_from_directory, session
from flask_cors import CORS # Import CORS
import fitz  # PyMuPDF
from dotenv import load_dotenv
import google.generativeai as genai
from google.generativeai import types as genai_types # For TTS config
import uuid # For generating unique filenames
import wave # For saving WAV files
import base64 # For decoding TTS audio data

load_dotenv()

app = Flask(__name__)
CORS(app) # Enable CORS for all routes
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your_very_secret_key_dev')

UPLOAD_FOLDER = 'uploads'
STATIC_FOLDER = 'static'
SLIDES_FOLDER = os.path.join(STATIC_FOLDER, 'slides')
AUDIO_FOLDER = os.path.join(STATIC_FOLDER, 'audio') # New folder for TTS audio
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['STATIC_FOLDER'] = STATIC_FOLDER
app.config['SLIDES_FOLDER'] = SLIDES_FOLDER
app.config['AUDIO_FOLDER'] = AUDIO_FOLDER

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SLIDES_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True) # Create audio folder

# Configure Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("FATAL: GEMINI_API_KEY not found in .env file. Please set it.")
else:
    genai.configure(api_key=GEMINI_API_KEY)
    print("Gemini API configured.")

# Helper function to save WAV file
def wave_file(filename, pcm, channels=1, rate=24000, sample_width=2):
   with wave.open(filename, "wb") as wf:
      wf.setnchannels(channels)
      wf.setsampwidth(sample_width)
      wf.setframerate(rate)
      wf.writeframes(pcm)

# --- Helper Functions ---
def pdf_to_images(pdf_path, output_folder):
    """Converts each page of a PDF to a PNG image."""
    pdf_filename_base = os.path.splitext(os.path.basename(pdf_path))[0]
    pdf_specific_slide_folder = os.path.join(output_folder, pdf_filename_base)
    
    if os.path.exists(pdf_specific_slide_folder):
        for f in os.listdir(pdf_specific_slide_folder):
            os.remove(os.path.join(pdf_specific_slide_folder, f))
    else:
        os.makedirs(pdf_specific_slide_folder, exist_ok=True)

    doc = fitz.open(pdf_path)
    image_paths = []
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        pix = page.get_pixmap()
        image_filename = f"slide_{page_num + 1}.png"
        image_path = os.path.join(pdf_specific_slide_folder, image_filename)
        pix.save(image_path)
        image_paths.append(os.path.join('slides', pdf_filename_base, image_filename))
    doc.close()
    return image_paths

# --- API Endpoints ---
@app.route('/upload', methods=['POST'])
def upload_pdf():
    if 'pdf' not in request.files:
        return jsonify({'error': 'No PDF file provided'}), 400
    file = request.files['pdf']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file and file.filename.endswith('.pdf'):
        original_filename = file.filename
        pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], original_filename)
        file.save(pdf_path)

        pdf_filename_base = os.path.splitext(original_filename)[0]
        session['pdf_filename_base'] = pdf_filename_base
        
        slide_image_paths = pdf_to_images(pdf_path, app.config['SLIDES_FOLDER'])
        return jsonify({'message': 'PDF processed successfully', 'slides': slide_image_paths, 'pdf_base': pdf_filename_base}), 200
    else:
        return jsonify({'error': 'Invalid file type. Only PDF is allowed.'}), 400

@app.route('/chat', methods=['POST'])
def chat_with_gemini():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    user_message = data.get('message')
    slide_image_path = data.get('slide_image_path') # Path relative to static folder

    if not user_message or not slide_image_path:
        return jsonify({'error': 'Missing message or slide_image_path'}), 400

    if not GEMINI_API_KEY:
        return jsonify({'error': 'Gemini API key not configured on the server.'}), 500
    
    full_slide_image_path = os.path.join(app.config['STATIC_FOLDER'], slide_image_path)

    if not os.path.exists(full_slide_image_path):
        return jsonify({'error': f'Slide image not found at {full_slide_image_path}'}), 404

    try:
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        
        slide_image_blob = {
            'mime_type': 'image/png',
            'data': open(full_slide_image_path, 'rb').read()
        }
        
        # The prompt should guide Gemini to focus on the image (slide)
        # and then answer the user's question about it.
        prompt_parts = [
            "You are a helpful assistant. The user has uploaded a slide from a presentation.",
            "Here is the slide:",
            slide_image_blob,
            f"The user's question about this slide is: {user_message}"
        ]
        
        response = model.generate_content(prompt_parts)
        
        # Ensure the response has text content
        if response.parts:
            gemini_reply = "".join(part.text for part in response.parts if hasattr(part, 'text'))
        else:
            # Fallback if no direct text part (might happen with safety filters, etc.)
            gemini_reply = "I couldn't generate a text response for this."
            if response.prompt_feedback and response.prompt_feedback.block_reason:
                gemini_reply += f" Reason: {response.prompt_feedback.block_reason_message}"


        return jsonify({'reply': gemini_reply}), 200

    except Exception as e:
        print(f"Error calling Gemini API for chat: {e}")
        # Check for specific Gemini API errors if available in the exception object
        # For example, if e has a 'message' attribute or similar
        error_message = str(e)
        if hasattr(e, 'message'): # Some Google API errors have a message attribute
            error_message = e.message
        elif hasattr(e, 'args') and e.args: # Generic exception arguments
             error_message = str(e.args[0])

        # Check for blocked prompt due to safety
        if " तुम्हारी सामग्री के लिए Safety attribution" in error_message or "response was blocked" in error_message.lower():
             gemini_reply = "My response was blocked due to safety settings. Please try rephrasing your question."
             return jsonify({'reply': gemini_reply}), 200 # Return a user-friendly message

        return jsonify({'error': f'Error communicating with Gemini for chat: {error_message}'}), 500


@app.route('/generate-slide-script', methods=['POST'])
def generate_slide_script():
    print("\n--- Received request for /generate-slide-script ---")
    data = request.get_json()
    if not data:
        print("Error: No data provided")
        return jsonify({'error': 'No data provided'}), 400
    slide_image_path = data.get('slide_image_path')
    print(f"Slide image path: {slide_image_path}")
    if not slide_image_path:
        print("Error: Missing slide_image_path")
        return jsonify({'error': 'Missing slide_image_path'}), 400

    if not GEMINI_API_KEY:
        print("Error: Gemini API key not configured.")
        return jsonify({'error': 'Gemini API key not configured.'}), 500
    
    full_slide_image_path = os.path.join(app.config['STATIC_FOLDER'], slide_image_path)
    if not os.path.exists(full_slide_image_path):
        print(f"Error: Slide image not found at {full_slide_image_path}")
        return jsonify({'error': f'Slide image not found at {full_slide_image_path}'}), 404

    try:
        print("Step 1: Generating script text...")
        script_generation_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        slide_image_blob = {
            'mime_type': 'image/png',
            'data': open(full_slide_image_path, 'rb').read()
        }
        script_prompt_parts = [
            "You are an excellent and engaging teacher. Create a script to present the following slide.",
            "The script should be clear, concise (about 100-150 words), and engaging.",
            "Focus only on the slide content. Do not invent external information.",
            "Here is the slide:",
            slide_image_blob,
            "Provide ONLY the teaching script text:"
        ]
        script_response = script_generation_model.generate_content(script_prompt_parts)
        print("Script generation API call complete.")
        script_text = ""
        if script_response.parts:
            script_text = "".join(part.text for part in script_response.parts if hasattr(part, 'text'))
            print(f"Generated script text (length: {len(script_text)}):")
            print(f"'{script_text[:200]}...'") # Print first 200 chars
        else:
            error_msg = "Could not generate a script text for this slide."
            if script_response.prompt_feedback and script_response.prompt_feedback.block_reason:
                error_msg += f" Reason: {script_response.prompt_feedback.block_reason_message}"
            print(f"Error during script generation: {error_msg}")
            return jsonify({'error': error_msg}), 500

        if not script_text.strip():
            print("Error: Generated script text was empty.")
            return jsonify({'error': "Generated script text was empty."}), 500

        print("\nStep 2: Converting script text to speech...")
        tts_model = genai.GenerativeModel("gemini-2.5-flash-preview-tts")
        
        try:
            tts_generation_config = {
                "response_modalities": ["AUDIO"],
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {
                            "voice_name": "Kore"
                        }
                    }
                }
            }
            print(f"TTS generation for script: '{script_text[:100]}...'")
            tts_response = tts_model.generate_content(
                contents=f"Say naturally and professionally: {script_text}",
                generation_config=tts_generation_config
            )
            print("TTS generation API call complete.")
            
            audio_data = tts_response.candidates[0].content.parts[0].inline_data.data
            
            audio_filename = f"script_audio_{uuid.uuid4()}.wav"
            audio_path = os.path.join(app.config['AUDIO_FOLDER'], audio_filename)
            
            print(f"Saving audio file to: {audio_path}")
            wave_file(audio_path, audio_data)
            print("Audio file saved.")
            
            print("--- Request to /generate-slide-script completed successfully ---")
            return jsonify({
                'script_text': script_text,
                'audio_url': f'/static/audio/{audio_filename}'
            }), 200

        except Exception as e:
            print(f"Error during Gemini TTS generation: {e}")
            import traceback
            traceback.print_exc()
            print("--- Request to /generate-slide-script completed with TTS error (returning script) ---")
            return jsonify({
                'script_text': script_text,
                'error': f'TTS generation failed: {str(e)}' 
            }), 200

    except Exception as e:
        print(f"Error in Gemini script generation (outer try-except): {e}")
        import traceback
        traceback.print_exc() 
        print("--- Request to /generate-slide-script failed (outer try-except) ---")
        return jsonify({'error': f'Error generating script: {str(e)}'}), 500


# Serve slide images
@app.route('/static/slides/<path:pdf_base>/<filename>')
def serve_slide_image(pdf_base, filename):
    pdf_slide_dir = os.path.join(app.config['SLIDES_FOLDER'], pdf_base)
    return send_from_directory(pdf_slide_dir, filename)

# Serve audio files
@app.route('/static/audio/<filename>')
def serve_audio_file(filename):
    return send_from_directory(app.config['AUDIO_FOLDER'], filename)

if __name__ == '__main__':
    app.run(debug=True, port=5001) # Run on a different port than common dev ports like 5000 or 3000 