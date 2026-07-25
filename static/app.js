document.addEventListener('DOMContentLoaded', () => {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const mainMenu = document.getElementById('main-menu');
    const authButton = document.getElementById('auth-button');
    const reauthBtn = document.getElementById('reauth-btn');
    const submitBtn = document.getElementById('submit-btn');
    const dateInput = document.getElementById('service-date');
    const publishDateInput = document.getElementById('publish-date');
    const timeInput = document.getElementById('publish-time');
    const statusDiv = document.getElementById('status');
    const authContainer = document.getElementById('auth-container');
    const themeToggleBtn = document.getElementById('theme-toggle');
    
    // Preview Elements
    const pcoPreview = document.getElementById('pco-preview');
    const previewThumb = document.getElementById('preview-thumb');
    const previewTitle = document.getElementById('preview-title');
    const previewDesc = document.getElementById('preview-desc');

    let selectedFile = null;

    // --- Dark Mode / Theme Setup ---
    const savedTheme = localStorage.getItem('theme') || 'dark';
    applyTheme(savedTheme);

    if (themeToggleBtn) {
        themeToggleBtn.addEventListener('click', () => {
            const isDark = document.body.classList.contains('dark-mode');
            const newTheme = isDark ? 'light' : 'dark';
            applyTheme(newTheme);
            localStorage.setItem('theme', newTheme);
        });
    }

    function applyTheme(theme) {
        if (theme === 'dark') {
            document.body.classList.add('dark-mode');
            if (themeToggleBtn) themeToggleBtn.textContent = '☀️ Light Mode';
        } else {
            document.body.classList.remove('dark-mode');
            if (themeToggleBtn) themeToggleBtn.textContent = '🌙 Dark Mode';
        }
    }

    // Set default initial values on page load to today
    if (dateInput && publishDateInput) {
        const todayStr = new Date().toISOString().split('T')[0];
        dateInput.value = todayStr;
        publishDateInput.value = todayStr;
        fetchPcoPreview(dateInput.value);
    }

    // Service Date Listener (Triggers PCO preview without touching publish date)
    if (dateInput) {
        dateInput.addEventListener('change', (e) => {
            if (e.target.value) {
                fetchPcoPreview(e.target.value);
            }
        });
    }

    function fetchPcoPreview(date) {
        if (!pcoPreview) return;
        pcoPreview.style.display = 'block';
        previewTitle.textContent = 'Loading Planning Center item...';
        previewDesc.textContent = '';
        previewThumb.style.display = 'none';

        fetch(`/pco-preview?date=${encodeURIComponent(date)}`)
            .then(res => res.json())
            .then(meta => {
                previewTitle.textContent = meta.title || 'No Title Found';
                previewDesc.textContent = meta.description || '';
                if (meta.thumbnail_url) {
                    console.log("Setting preview image URL:", meta.thumbnail_url);
                    previewThumb.src = meta.thumbnail_url;
                    previewThumb.style.display = 'block';
                } else {
                    console.log("No thumbnail URL received from backend.");
                    previewThumb.style.display = 'none';
                }
            })
            .catch(err => {
                console.error("Preview fetch error:", err);
                previewTitle.textContent = 'Failed to load preview metadata.';
            });
    }

    checkAuthentication();

    function checkAuthentication() {
        fetch('/check-auth')
            .then(res => {
                if (!res.ok) throw new Error('Server returned an HTTP error status');
                return res.json();
            })
            .then(data => {
                if (data.authenticated) {
                    if (authContainer) authContainer.style.display = 'none';
                    if (mainMenu) mainMenu.style.display = 'block';
                    if (statusDiv) statusDiv.style.display = 'none';
                } else {
                    if (authContainer) authContainer.style.display = 'block';
                    if (mainMenu) mainMenu.style.display = 'none';
                    showStatus('Action Required: Please complete YouTube authorization flow setup.', 'error');
                }
            })
            .catch(err => {
                console.error("Frontend Initialization Error:", err);
                showStatus('Error connecting to backend server environment. Check your Docker port bindings.', 'error');
            });
    }

    // Setup Auth Flow Redirection Popup
    if (authButton) {
        authButton.addEventListener('click', () => {
            showStatus('Opening YouTube login flow window...', 'success');
            window.open('/auth', 'YouTubeAuth', 'width=600,height=700');
        });
    }

    // Switch Account / Re-authenticate Handler
    if (reauthBtn) {
        reauthBtn.addEventListener('click', () => {
            fetch('/logout', { method: 'POST' })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        showStatus('Opening YouTube re-authorization window...', 'success');
                        window.open('/auth', 'YouTubeAuth', 'width=600,height=700');
                    }
                })
                .catch(err => console.error("Logout error:", err));
        });
    }

    // Drag and Drop implementation
    if (dropZone) {
        dropZone.addEventListener('click', () => fileInput.click());
        dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('hover'); });
        dropZone.addEventListener('dragleave', () => dropZone.classList.remove('hover'));
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('hover');
            if (e.dataTransfer.files.length) {
                selectedFile = e.dataTransfer.files[0];
                dropZone.textContent = `Selected: ${selectedFile.name}`;
            }
        });
    }

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length) {
            selectedFile = fileInput.files[0];
            dropZone.textContent = `Selected: ${selectedFile.name}`;
        }
    });

    if (submitBtn) {
        submitBtn.addEventListener('click', () => {
            if (!selectedFile || !dateInput.value) {
                showStatus('Please choose a file and select a date.', 'error');
                return;
            }

            const formData = new FormData();
            formData.append('video', selectedFile);
            formData.append('date', dateInput.value);
            formData.append('publish_date', publishDateInput.value || dateInput.value);
            formData.append('publish_time', timeInput.value || '13:00');

            showStatus('Processing metadata and transferring video streams...', 'success');

            fetch('/upload', {
                method: 'POST',
                body: formData
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    showStatus(`Successfully published! Title: "${data.metadata.title}"`, 'success');
                } else {
                    showStatus(`Upload execution failed: ${data.error}`, 'error');
                }
            })
            .catch(() => showStatus('An error occurred during communication with server environment.', 'error'));
        });
    }

    function showStatus(msg, type) {
        statusDiv.textContent = msg;
        statusDiv.className = `card ${type}`;
        statusDiv.style.display = 'block';

        if (type === 'success') {
            setTimeout(() => {
                statusDiv.style.display = 'none';
            }, 5000);
        }
    }
});