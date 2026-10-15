import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom' // 1. Importas el enrutador aquí
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {/* 2. Envuelves la App completa */}
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)