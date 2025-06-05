document.addEventListener('DOMContentLoaded', () => {
    const pdfUploadInput = document.getElementById('pdf-upload');
    const uploadButton = document.getElementById('upload-button');
    const uploadStatus = document.getElementById('upload-status');

    const slideshowSection = document.getElementById('slideshow-section');
    const currentSlideImage = document.getElementById('current-slide-image');
    const prevSlideButton = document.getElementById('prev-slide');
    const nextSlideButton = document.getElementById('next-slide');
    const slideInfo = document.getElementById('slide-info');

    const presentSlideButton = document.getElementById('present-slide-button');

    const chatSection = document.getElementById('chat-section');
    const chatHistory = document.getElementById('chat-history');
    const chatMessageInput = document.getElementById('chat-message');
    const sendChatButton = document.getElementById('send-chat-button');

    let currentSlides = [];
    let currentSlideIndex = 0;
    const API_BASE_URL = 'http://localhost:5001'; // Backend URL
    
    // Audio player management
    let audioPlayer = null; // To hold the HTMLAudioElement
    let currentlyPlayingAudioUrl = null;

    function displayUploadStatus(message, isError = false) {
        uploadStatus.textContent = message;
        uploadStatus.style.color = isError ? 'red' : 'green';
    }

    function updateSlideView() {
        stopAudioPresentation(); // Stop audio if slide changes
        if (currentSlides.length > 0) {
            currentSlideImage.src = `${API_BASE_URL}/static/${currentSlides[currentSlideIndex]}`;
            slideInfo.textContent = `Slide ${currentSlideIndex + 1} of ${currentSlides.length}`;
            slideshowSection.classList.remove('hidden');
            chatSection.classList.remove('hidden');
            presentSlideButton.disabled = false;
            chatHistory.innerHTML = ''; 
            chatMessageInput.value = '';
        } else {
            slideshowSection.classList.add('hidden');
            chatSection.classList.add('hidden');
            presentSlideButton.disabled = true;
        }
        prevSlideButton.disabled = currentSlideIndex === 0;
        nextSlideButton.disabled = currentSlideIndex === currentSlides.length - 1;
    }

    uploadButton.addEventListener('click', async () => {
        stopAudioPresentation();
        const file = pdfUploadInput.files[0];
        if (!file) {
            displayUploadStatus('Please select a PDF file.', true);
            return;
        }
        if (file.type !== "application/pdf") {
            displayUploadStatus('Invalid file type. Please upload a PDF.', true);
            return;
        }

        displayUploadStatus('Uploading and processing PDF...');
        const formData = new FormData();
        formData.append('pdf', file);

        try {
            const response = await fetch(`${API_BASE_URL}/upload`, {
                method: 'POST',
                body: formData,
            });
            const result = await response.json();
            if (response.ok) {
                displayUploadStatus(result.message || 'PDF processed successfully!');
                currentSlides = result.slides || [];
                currentSlideIndex = 0;
                updateSlideView();
            } else {
                displayUploadStatus(result.error || 'Failed to process PDF.', true);
                currentSlides = [];
                presentSlideButton.disabled = true;
                updateSlideView();
            }
        } catch (error) {
            console.error('Upload error:', error);
            displayUploadStatus('An error occurred during upload. Check console.', true);
            currentSlides = [];
            presentSlideButton.disabled = true;
            updateSlideView();
        }
    });

    prevSlideButton.addEventListener('click', () => {
        if (currentSlideIndex > 0) {
            currentSlideIndex--;
            updateSlideView();
        }
    });

    nextSlideButton.addEventListener('click', () => {
        if (currentSlideIndex < currentSlides.length - 1) {
            currentSlideIndex++;
            updateSlideView();
        }
    });

    function stopAudioPresentation() {
        if (audioPlayer) {
            audioPlayer.pause();
            audioPlayer.src = ''; // Release the audio file
            audioPlayer.remove(); // Remove element from DOM to be sure
            audioPlayer = null;
        }
        currentlyPlayingAudioUrl = null;
        presentSlideButton.textContent = '🎤 Present Slide';
        presentSlideButton.disabled = currentSlides.length === 0;
    }

    presentSlideButton.addEventListener('click', async () => {
        if (currentSlides.length === 0) return;

        const currentSlidePath = currentSlides[currentSlideIndex];

        // If audio is playing for the current slide, toggle pause/play
        // Or if it's a different slide, it would have been stopped by updateSlideView
        if (audioPlayer && !audioPlayer.paused && currentlyPlayingAudioUrl === `${API_BASE_URL}/static/${currentSlidePath}`) {
            audioPlayer.pause();
            presentSlideButton.textContent = '▶️ Resume Presentation';
            return;
        } else if (audioPlayer && audioPlayer.paused && currentlyPlayingAudioUrl === `${API_BASE_URL}/static/${currentSlidePath}`) {
            audioPlayer.play();
            presentSlideButton.textContent = '❚❚ Pause Presentation';
            return;
        }

        // If here, we need to fetch new audio or play for the first time for this slide
        stopAudioPresentation(); // Ensure any previous audio is stopped

        presentSlideButton.disabled = true;
        presentSlideButton.textContent = '⏳ Loading Audio...';

        try {
            const response = await fetch(`${API_BASE_URL}/generate-slide-script`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    slide_image_path: currentSlidePath
                }),
            });
            const result = await response.json();

            if (response.ok && result.audio_url) {
                audioPlayer = new Audio(API_BASE_URL + result.audio_url); // Prepend base URL if not already there
                currentlyPlayingAudioUrl = API_BASE_URL + result.audio_url;

                audioPlayer.oncanplaythrough = () => {
                    presentSlideButton.textContent = '❚❚ Pause Presentation';
                    presentSlideButton.disabled = false;
                    audioPlayer.play();
                };
                audioPlayer.onended = () => {
                    stopAudioPresentation(); // Resets button and player
                };
                audioPlayer.onerror = (e) => {
                    console.error('Audio player error:', e);
                    addMessageToChat('Error playing audio. See console.', 'gemini');
                    stopAudioPresentation();
                };
                audioPlayer.load(); // Start loading the audio
                // Optional: display the script text if needed (result.script_text)
                // console.log("Generated script: ", result.script_text);

            } else {
                addMessageToChat(result.error || 'Could not load audio script.', 'gemini');
                stopAudioPresentation(); // Reset button state
            }
        } catch (error) {
            console.error('Error fetching audio script:', error);
            addMessageToChat('Failed to fetch audio script. Check console.', 'gemini');
            stopAudioPresentation(); // Reset button state
        }
    });

    function addMessageToChat(message, sender) {
        const messageElement = document.createElement('div');
        messageElement.classList.add('chat-message', sender === 'user' ? 'user-message' : 'gemini-message');
        const senderStrong = document.createElement('strong');
        senderStrong.textContent = sender === 'user' ? 'You: ' : 'Gemini: ';
        messageElement.appendChild(senderStrong);
        messageElement.appendChild(document.createTextNode(message));
        chatHistory.appendChild(messageElement);
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    async function handleSendMessage() {
        const message = chatMessageInput.value.trim();
        if (!message || currentSlides.length === 0) {
            return;
        }
        addMessageToChat(message, 'user');
        chatMessageInput.value = '';
        const currentSlidePath = currentSlides[currentSlideIndex];
        try {
            addMessageToChat('Thinking...', 'gemini-thinking');
            const response = await fetch(`${API_BASE_URL}/chat`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    message: message,
                    slide_image_path: currentSlidePath
                }),
            });
            const thinkingMessage = chatHistory.querySelector('.gemini-message:last-child');
            if (thinkingMessage && thinkingMessage.textContent.includes('Thinking...')) {
                chatHistory.removeChild(thinkingMessage);
            }
            const result = await response.json();
            if (response.ok) {
                addMessageToChat(result.reply, 'gemini');
            } else {
                addMessageToChat(result.error || 'Error communicating with Gemini.', 'gemini');
            }
        } catch (error) {
            console.error('Chat error:', error);
            const thinkingMessage = chatHistory.querySelector('.gemini-message:last-child');
            if (thinkingMessage && thinkingMessage.textContent.includes('Thinking...')) {
                chatHistory.removeChild(thinkingMessage);
            }
            addMessageToChat('Failed to send message. Check console.', 'gemini');
        }
    }

    sendChatButton.addEventListener('click', handleSendMessage);
    chatMessageInput.addEventListener('keypress', (event) => {
        if (event.key === 'Enter') {
            handleSendMessage();
        }
    });

    updateSlideView();
}); 