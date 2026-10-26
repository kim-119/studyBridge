import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import './index.css'
import { shouldUsePhoneFrame, mountPhoneFrame, syncPhoneFrameParent } from './utils/phoneFrame'

// m. 호스트를 데스크톱에서 열면 앱을 휴대폰 폭 프레임 안에서 띄워 모바일 웹 화면을 보여준다(utils/phoneFrame.js).
if (shouldUsePhoneFrame(window)) {
  mountPhoneFrame(window, document)
} else {
  syncPhoneFrameParent(window)
  ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </React.StrictMode>,
  )
}
