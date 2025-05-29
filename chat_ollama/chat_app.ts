// BIG FAT WARNING: to avoid the complexity of npm, this typescript is compiled in the browser
// there's currently no static type checking

console.log("chat_app.ts module execution started"); // New log

import { marked } from 'https://cdnjs.cloudflare.com/ajax/libs/marked/15.0.0/lib/marked.esm.js'
const convElement = document.getElementById('conversation')
const promptInput = document.getElementById('prompt-input') as HTMLTextAreaElement
const spinner = document.getElementById('spinner')
const errorElement = document.getElementById('error')
const formElement = document.querySelector('form')
const modelSelectElement = document.getElementById('model-select') as HTMLSelectElement
const clearChatButton = document.getElementById('clear-chat-btn')
const themeToggle = document.getElementById('theme-checkbox') as HTMLInputElement

// Theme handling
function applyTheme(theme: string) {
    if (theme === 'dark') {
        document.body.classList.add('dark-theme');
        if (themeToggle) themeToggle.checked = true;
    } else {
        document.body.classList.remove('dark-theme');
        if (themeToggle) themeToggle.checked = false;
    }
}

function toggleTheme() {
    if (themeToggle && themeToggle.checked) {
        localStorage.setItem('theme', 'dark');
        applyTheme('dark');
    } else {
        localStorage.setItem('theme', 'light');
        applyTheme('light');
    }
}

// Apply saved theme on load
const savedTheme = localStorage.getItem('theme') || 'light'; // Default to light
applyTheme(savedTheme);

if (themeToggle) {
    themeToggle.addEventListener('change', toggleTheme);
}

// stream the response and render messages as each chunk is received
// data is sent as newline-delimited JSON
async function onFetchResponse(response: Response): Promise<void> {
  let text = ''
  let decoder = new TextDecoder()
  if (response.ok) {
    const reader = response.body?.getReader()
    if (!reader) {
        console.error('Response body is null');
        onError(new Error('Response body is null'));
        return;
    }
    try {
        while (true) {
            const {done, value} = await reader.read()
            if (done) {
                break
            }
            text += decoder.decode(value)
            // Process incrementally, but handle potential partial JSON objects by trying to process the whole `text` so far
            // More robust streaming would parse line by line if each line is a distinct JSON
            addMessages(text) 
            if (spinner) spinner.classList.remove('active')
        }
        // Final processing of any remaining text
        addMessages(text) 
        if (promptInput) {
            promptInput.disabled = false
            promptInput.focus()
        }
    } catch (streamError) {
        console.error("Error processing stream:", streamError);
        onError(streamError);
    }
  } else {
    const errorText = await response.text()
    console.error(`Unexpected response: ${response.status}`, {response, errorText})
    onError(new Error(`Unexpected response: ${response.statusText || response.status} - ${errorText}`))
  }
}

// The format of messages, this matches pydantic-ai both for brevity and understanding
// in production, you might not want to keep this format all the way to the frontend
interface Message {
  role: string
  content: string
  timestamp: string
}

// take raw response text and render messages into the `#conversation` element
// Message timestamp is assumed to be a unique identifier of a message, and is used to deduplicate
// hence you can send data about the same message multiple times, and it will be updated
// instead of creating a new message elements
function addMessages(responseText: string) {
    const lines = responseText.split('\n');
    const potentialMessages = lines.filter(line => line.trim().startsWith('{') && line.trim().endsWith('}'));

    for (const line of potentialMessages) {
        let message: Message | null = null;
        try {
            message = JSON.parse(line) as Message;
        } catch (e) {
            console.warn('Skipping invalid JSON line:', line, e);
            continue; // Skip this line if it's not valid JSON
        }

        if (!message || !message.timestamp || !message.role || typeof message.content === 'undefined') {
            console.warn('Skipping malformed message object:', message);
            continue;
        }

        const {timestamp, role, content} = message;
        const id = `msg-${timestamp.replace(/[:.]/g, '-')}`;
        let msgDiv = document.getElementById(id);

        let htmlContent = '';
        try {
            htmlContent = marked.parse(content) as string;
        } catch (e) {
            console.error('Error parsing markdown:', content, e);
            htmlContent = content; // Fallback to raw content
        }

        if (!msgDiv) {
            msgDiv = document.createElement('div');
            msgDiv.id = id;
            msgDiv.classList.add('message', role === 'user' ? 'user' : 'model');
            
            const contentDiv = document.createElement('div');
            contentDiv.classList.add('message-content');
            contentDiv.innerHTML = htmlContent;
            msgDiv.appendChild(contentDiv);

            const metaDiv = document.createElement('div');
            metaDiv.classList.add('message-meta');
            const date = new Date(timestamp);
            metaDiv.textContent = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            msgDiv.appendChild(metaDiv);
            
            if (convElement) convElement.appendChild(msgDiv);
        } else {
            const contentDiv = msgDiv.querySelector('.message-content');
            if (contentDiv) {
                contentDiv.innerHTML = htmlContent;
            }
        }
    }
    if (convElement) {
        convElement.scrollTop = convElement.scrollHeight;
    }
}

function onError(error: any) {
  // Try to make the error visible in the UI in the simplest way possible
  const errEl = document.getElementById('error');
  if (errEl) {
    errEl.textContent = "BASIC onError CALLED. See console if anything else appears.";
    errEl.classList.remove('d-none');
  } else {
    // If errEl is null, this alert is a last resort to show onError was called
    alert("onError called, but error div not found!");
  }
  
  // Only one console log to minimize potential console issues
  console.log("BASIC ON_ERROR_LOG: ", error);

  // We are intentionally not manipulating spinner or promptInput here for this test
}

async function onSubmit(e: SubmitEvent): Promise<void> {
  e.preventDefault()
  if (spinner) spinner.classList.add('active')
  if (errorElement) errorElement.classList.add('d-none'); // Hide error on new submit

  const form = e.target as HTMLFormElement
  const body = new FormData(form)

  if (modelSelectElement) {
    body.set('model_name', modelSelectElement.value);
  }

  if (promptInput) {
    promptInput.value = ''
    promptInput.disabled = true
  }
  const fileInput = form.querySelector('input[type="file"]') as HTMLInputElement
  if (fileInput) {
    fileInput.value = ''
  }

  try {
    const response = await fetch('/chat/', {method: 'POST', body})
    await onFetchResponse(response)
  } catch (error) {
    onError(error)
  }
}

if (formElement) {
    formElement.addEventListener('submit', (e: Event) => onSubmit(e as SubmitEvent).catch(onError))
}

// load messages on page load
if (errorElement) errorElement.classList.add('d-none'); // Hide error initially
fetch('/chat/').then(onFetchResponse).catch(onError)

// Populate model dropdown
const DEFAULT_FRONTEND_MODEL = 'qwen2.5vl:72b-q4_K_M'; // Fallback if needed

async function populateModels() {
    if (!modelSelectElement) return;
    try {
        const response = await fetch('/models/');
        if (response.ok) {
            const models: string[] = await response.json();
            modelSelectElement.innerHTML = ''; // Clear existing options (like "Loading...")
            if (models.length === 0) {
                const option = document.createElement('option');
                option.value = DEFAULT_FRONTEND_MODEL;
                option.textContent = DEFAULT_FRONTEND_MODEL + " (default - no models found)";
                option.selected = true;
                modelSelectElement.appendChild(option);
            } else {
                let defaultModelFound = false;
                models.forEach(modelName => {
                    const option = document.createElement('option');
                    option.value = modelName;
                    option.textContent = modelName;
                    if (modelName === DEFAULT_FRONTEND_MODEL) {
                        option.selected = true;
                        defaultModelFound = true;
                    }
                    modelSelectElement.appendChild(option);
                });
                if (!defaultModelFound && modelSelectElement.options.length > 0) {
                     modelSelectElement.options[0].selected = true; // Select first if default not found
                }
            }
        } else {
            console.error("Failed to fetch models:", response.status);
            modelSelectElement.innerHTML = '<option value="" disabled selected>Error loading models</option>';
        }
    } catch (error) {
        console.error("Error fetching or populating models:", error);
        modelSelectElement.innerHTML = '<option value="" disabled selected>Error loading models</option>';
    }
}

populateModels();

// Clear chat button logic
if (clearChatButton) {
    clearChatButton.addEventListener('click', async () => {
        if (confirm("Are you sure you want to clear all chat history?")) {
            if(spinner) spinner.classList.add('active');
            if (errorElement) errorElement.classList.add('d-none'); // Hide error
            try {
                const response = await fetch('/chat/', { method: 'DELETE' })
                if (response.ok) {
                    if (convElement) convElement.innerHTML = '' // Clear frontend display
                } else {
                    const errorText = await response.text();
                    console.error('Failed to clear chat history:', response.status, errorText)
                    alert(`Failed to clear chat history: ${errorText}`)
                }
            } catch (error) {
                console.error('Error clearing chat history:', error)
                onError(error) // Reuse existing error display logic
            }
            if(spinner) spinner.classList.remove('active')
        }
    })
} 