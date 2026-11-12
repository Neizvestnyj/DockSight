import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './shared/styles/fonts.css';
import './shared/styles/base.css';
import App from './app/App';
import './shared/styles/responsive.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
