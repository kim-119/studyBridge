import React from 'react';
import ReactDOM from 'react-dom/client';
import { HashRouter } from 'react-router-dom';
import MobileApp from './MobileApp.jsx';
import ErrorBoundary from './components/ErrorBoundary';
import '../index.css';
import './mobile.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <HashRouter>
        <MobileApp />
      </HashRouter>
    </ErrorBoundary>
  </React.StrictMode>
);
