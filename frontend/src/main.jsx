import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import './styles.css'
import './theme.css'
function ThemeShell() {
  const [theme, setTheme] = useState(() => localStorage.getItem('nodeflow.theme') || 'dark')
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem('nodeflow.theme', theme) }, [theme])
  return <><App /><button className="theme-toggle" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}><span>{theme === 'dark' ? '☀' : '☾'}</span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</button></>
}

createRoot(document.getElementById('root')).render(<StrictMode><ThemeShell /></StrictMode>)
