import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { installStartupResumeHandlers, requestStartupWake } from './services/startupWake'

// Start the independent free-service cold starts together. This is a
// best-effort wake/readiness request only; it never starts camera analysis.
requestStartupWake()
installStartupResumeHandlers()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
