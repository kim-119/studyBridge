import React, { useState } from 'react';
import {
  Users, User, X, MicOff, Video, VideoOff, Maximize, Minimize, Gift, UserPlus,
  Settings, MessageSquare, Calendar, ClipboardList, Mic,
  Search, AlertTriangle, Play, RefreshCw, VolumeX, Volume2, Monitor, Edit2, Send, Check
} from 'lucide-react';

export default function StudyRoom({ study, onClose }) {
  const [activeTab, setActiveTab] = useState('chat');
  const [isMicOn, setIsMicOn] = useState(false);
  const [isVideoOn, setIsVideoOn] = useState(true);
  const [showSettings, setShowSettings] = useState(false);
  const [showStatsModal, setShowStatsModal] = useState(false);
  const [showRoomManageModal, setShowRoomManageModal] = useState(false);
  const [roomManageTab, setRoomManageTab] = useState('settings'); // 'settings' | 'members'
  const [showAdminReportModal, setShowAdminReportModal] = useState(false);
  const [adminReportTab, setAdminReportTab] = useState('inquiry'); // 'inquiry' | 'report'
  const [isCamFullScreen, setIsCamFullScreen] = useState(false);

  // 커스텀 모달 상태
  const [customAlert, setCustomAlert] = useState({
    isOpen: false,
    title: '',
    message: '',
    type: 'alert',
    inputPlaceholder: '',
    inputValue: '',
    onConfirm: null,
    onCancel: null,
  });

  const showAlert = (title, message, onConfirm = null) => {
    setCustomAlert({ isOpen: true, title, message, type: 'alert', onConfirm: () => { setCustomAlert(prev => ({ ...prev, isOpen: false })); if (onConfirm) onConfirm(); } });
  };

  const showConfirm = (title, message, onConfirm) => {
    setCustomAlert({ isOpen: true, title, message, type: 'confirm', onConfirm: () => { setCustomAlert(prev => ({ ...prev, isOpen: false })); onConfirm(); }, onCancel: () => setCustomAlert(prev => ({ ...prev, isOpen: false })) });
  };

  const showPrompt = (title, message, inputPlaceholder, onConfirm) => {
    setCustomAlert({ isOpen: true, title, message, type: 'prompt', inputPlaceholder, inputValue: '', onConfirm: (val) => { setCustomAlert(prev => ({ ...prev, isOpen: false })); onConfirm(val); }, onCancel: () => setCustomAlert(prev => ({ ...prev, isOpen: false })) });
  };

  return (
    <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 99999, backgroundColor: '#0B0F19', display: 'flex', flexDirection: 'column', color: 'white', fontFamily: "'Inter', sans-serif" }}>
      <style>{`
        .custom-scrollbar::-webkit-scrollbar {
          width: 6px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: rgba(255, 255, 255, 0.02);
          border-radius: 4px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: rgba(255, 255, 255, 0.1);
          border-radius: 4px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background: rgba(255, 255, 255, 0.2);
        }
        .custom-scrollbar {
          scrollbar-width: thin;
          scrollbar-color: rgba(255, 255, 255, 0.1) rgba(255, 255, 255, 0.02);
        }
      `}</style>

      {/* Header - Glassmorphic Dark */}
      {!isCamFullScreen && (
        <div style={{ height: '60px', backgroundColor: 'rgba(15, 23, 42, 0.7)', backdropFilter: 'blur(16px)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 24px', borderBottom: '1px solid rgba(255,255,255,0.08)', zIndex: 10 }}>

          <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
            {/* Text Logo Area */}
            <div style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', gap: '6px' }}>
              <span style={{ fontSize: '20px', fontWeight: '900', letterSpacing: '-0.5px', background: 'linear-gradient(90deg, #84cc16, #eab308, #f97316)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
                StudyBridge
              </span>
            </div>

            <div style={{ width: '1px', height: '20px', backgroundColor: 'rgba(255,255,255,0.1)' }} />

            {/* Title Area */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <h1 style={{ margin: 0, color: '#F3F4F6', fontSize: '16px', fontWeight: '600' }}>{study.title}</h1>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', backgroundColor: 'rgba(59, 130, 246, 0.15)', color: '#60A5FA', padding: '4px 10px', borderRadius: '12px', fontSize: '12px', fontWeight: '600' }}>
                <Users size={14} /> {study.currentMembers || 2} / {study.maxMembers || 16}
              </div>
            </div>
          </div>

          {/* Right Controls */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', backgroundColor: 'rgba(255,255,255,0.05)', padding: '6px 12px', borderRadius: '20px' }}>
              <div onClick={() => setIsMicOn(!isMicOn)} style={{ display: 'flex', alignItems: 'center' }}>
                {isMicOn ? <Mic size={18} color="#D1D5DB" cursor="pointer" /> : <MicOff size={18} color="#F87171" cursor="pointer" />}
              </div>
              <div onClick={() => setIsVideoOn(!isVideoOn)} style={{ display: 'flex', alignItems: 'center' }}>
                {isVideoOn ? <Video size={18} color="#D1D5DB" cursor="pointer" /> : <VideoOff size={18} color="#F87171" cursor="pointer" />}
              </div>
              <Settings size={18} color="#D1D5DB" cursor="pointer" onClick={() => setShowSettings(true)} />
            </div>

            <div style={{ width: '1px', height: '20px', backgroundColor: 'rgba(255,255,255,0.1)' }} />

            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <Maximize size={18} color="#9CA3AF" cursor="pointer" onClick={() => setIsCamFullScreen(true)} />
              <div
                onClick={onClose}
                style={{ width: '32px', height: '32px', borderRadius: '50%', backgroundColor: 'rgba(239, 68, 68, 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', transition: 'all 0.2s' }}
                onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(239, 68, 68, 0.2)'}
                onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'rgba(239, 68, 68, 0.1)'}
              >
                <X size={16} color="#EF4444" />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Main Body */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* Left Sidebar - Floating Dock Style */}
        {!isCamFullScreen && (
          <div style={{ width: '72px', backgroundColor: '#0F172A', display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '24px 0', borderRight: '1px solid rgba(255,255,255,0.05)' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', alignItems: 'center' }}>
              <div onClick={() => setShowStatsModal(true)} style={{ padding: '10px', borderRadius: '12px', color: '#9CA3AF', cursor: 'pointer', transition: '0.2s', ':hover': { color: 'white', backgroundColor: 'rgba(255,255,255,0.1)' } }}>
                <Calendar size={22} />
              </div>
              <div onClick={() => setShowRoomManageModal(true)} style={{ padding: '10px', borderRadius: '12px', color: '#9CA3AF', cursor: 'pointer', transition: '0.2s', ':hover': { color: 'white', backgroundColor: 'rgba(255,255,255,0.1)' } }}>
                <ClipboardList size={22} />
              </div>
            </div>

            <div style={{ marginTop: 'auto' }}>
              <div
                style={{ padding: '10px', borderRadius: '12px', backgroundColor: 'rgba(59, 130, 246, 0.2)', color: '#60A5FA', cursor: 'pointer', boxShadow: '0 0 15px rgba(59, 130, 246, 0.1)' }}
                onClick={() => setShowAdminReportModal(true)}
              >
                <MessageSquare size={22} />
              </div>
            </div>
          </div>
        )}

        {/* Video Grid */}
        <div className="custom-scrollbar" style={{ flex: 1, padding: '24px', overflowY: 'auto', backgroundColor: '#0B0F19', position: 'relative' }}>

          {isCamFullScreen && (
            <div
              style={{ position: 'fixed', top: '24px', right: '24px', zIndex: 1000, backgroundColor: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', padding: '8px 16px', borderRadius: '24px', border: '1px solid rgba(255,255,255,0.1)', display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', transition: '0.2s', boxShadow: '0 4px 12px rgba(0,0,0,0.5)' }}
              onClick={() => setIsCamFullScreen(false)}
              onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(0,0,0,0.8)'}
              onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'rgba(0,0,0,0.6)'}
            >
              <Minimize size={16} color="#E5E7EB" />
              <span style={{ color: '#E5E7EB', fontSize: '13px', fontWeight: '600' }}>전체화면 종료</span>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '20px', height: '100%', alignContent: 'start' }}>

            {/* Slot 1: Active user */}
            <div style={{ position: 'relative', backgroundColor: '#1E293B', borderRadius: '16px', overflow: 'hidden', aspectRatio: '16/9', border: '1px solid rgba(255,255,255,0.05)', boxShadow: '0 10px 30px rgba(0,0,0,0.3)' }}>
              <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundImage: 'url(https://images.unsplash.com/photo-1516321318423-f06f85e504b3?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80)', backgroundSize: 'cover', backgroundPosition: 'center' }} />

              <div style={{ position: 'absolute', top: '12px', left: '12px', backgroundColor: 'rgba(15, 23, 42, 0.6)', backdropFilter: 'blur(8px)', padding: '4px 10px', borderRadius: '20px', display: 'flex', alignItems: 'center', gap: '6px', border: '1px solid rgba(255,255,255,0.1)' }}>
                <div style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#F87171', boxShadow: '0 0 8px #F87171' }} />
                <span style={{ color: 'white', fontSize: '11px', fontWeight: '600' }}>00:10:35</span>
              </div>

              <div style={{ position: 'absolute', top: '12px', right: '12px', backgroundColor: 'rgba(15, 23, 42, 0.6)', backdropFilter: 'blur(8px)', padding: '4px 10px', borderRadius: '20px', display: 'flex', alignItems: 'center', gap: '6px', border: '1px solid rgba(255,255,255,0.1)' }}>
                <Play size={10} color="#60A5FA" />
                <span style={{ color: 'white', fontSize: '11px', fontWeight: '600' }}>00:00:00</span>
              </div>

              <div style={{ position: 'absolute', bottom: '0', left: '0', right: '0', padding: '24px 12px 12px', background: 'linear-gradient(to top, rgba(0,0,0,0.8), transparent)', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
                <span style={{ color: 'white', fontSize: '14px', fontWeight: '600', textShadow: '0 2px 4px rgba(0,0,0,0.5)' }}>mindcontrol</span>
                <div style={{ backgroundColor: 'rgba(239, 68, 68, 0.2)', padding: '6px', borderRadius: '50%', backdropFilter: 'blur(4px)' }}>
                  <MicOff size={14} color="#F87171" />
                </div>
              </div>
            </div>

            {/* Slot 2: Camera Off */}
            <div style={{ position: 'relative', backgroundColor: '#1E293B', borderRadius: '16px', overflow: 'hidden', aspectRatio: '16/9', border: '1px solid rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 15px rgba(0,0,0,0.2)' }}>
              <div style={{ width: '64px', height: '64px', borderRadius: '50%', backgroundColor: '#334155', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 8px 24px rgba(0,0,0,0.4)' }}>
                <User size={32} color="#9CA3AF" />
              </div>
              <div style={{ position: 'absolute', bottom: '0', left: '0', right: '0', padding: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', backgroundColor: 'rgba(15, 23, 42, 0.6)', padding: '4px 12px', borderRadius: '20px' }}>
                  <span style={{ color: '#FCD34D', fontSize: '13px', fontWeight: '600' }}>잠재용</span>
                </div>
                <div style={{ backgroundColor: 'rgba(239, 68, 68, 0.2)', padding: '6px', borderRadius: '50%' }}>
                  <MicOff size={14} color="#F87171" />
                </div>
              </div>
            </div>

            {/* Empty Slots */}
            {Array.from({ length: 14 }).map((_, i) => (
              <div key={i} style={{ backgroundColor: 'rgba(30, 41, 59, 0.3)', borderRadius: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', aspectRatio: '16/9', border: '1px dashed rgba(255,255,255,0.1)' }}>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px', opacity: 0.3 }}>
                  <Monitor size={36} color="#9CA3AF" />
                  <span style={{ color: '#9CA3AF', fontSize: '14px', fontWeight: '600', letterSpacing: '0.5px' }}>StudyBridge</span>
                </div>
              </div>
            ))}

          </div>
        </div>

        {/* Right Sidebar - Chat & Participants */}
        {!isCamFullScreen && (
          <div style={{ width: '340px', backgroundColor: '#0F172A', display: 'flex', flexDirection: 'column', borderLeft: '1px solid rgba(255,255,255,0.05)' }}>

            {/* Participants Area */}
            <div style={{ padding: '20px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <div style={{ fontSize: '14px', fontWeight: '700', color: '#F3F4F6', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  참여자 목록
                  <span style={{ backgroundColor: 'rgba(59, 130, 246, 0.2)', color: '#60A5FA', padding: '2px 8px', borderRadius: '10px', fontSize: '12px' }}>2 / {study.maxMembers || 16}</span>
                </div>
                <div style={{ padding: '6px', backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: '8px', cursor: 'pointer' }}>
                  <Search size={14} color="#9CA3AF" />
                </div>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px', borderRadius: '12px', backgroundColor: 'rgba(255,255,255,0.02)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{ width: '32px', height: '32px', borderRadius: '50%', backgroundImage: 'url(https://images.unsplash.com/photo-1534528741775-53994a69daeb?ixlib=rb-4.0.3&auto=format&fit=crop&w=100&q=80)', backgroundSize: 'cover', border: '2px solid #3B82F6' }} />
                    <span style={{ fontSize: '13px', color: '#E5E7EB', fontWeight: '500' }}>mindcontrol</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <Video size={14} color="#9CA3AF" />
                    <MicOff size={14} color="#F87171" />
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px', borderRadius: '12px', backgroundColor: 'rgba(255,255,255,0.02)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{ width: '32px', height: '32px', borderRadius: '50%', backgroundColor: '#334155', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <User size={16} color="#9CA3AF" />
                    </div>
                    <span style={{ fontSize: '13px', color: '#E5E7EB', fontWeight: '500' }}>잠재용</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <Video size={14} color="#9CA3AF" />
                    <MicOff size={14} color="#F87171" />
                  </div>
                </div>
              </div>
            </div>

            {/* Chat Area */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', backgroundColor: '#111827' }}>
              <div style={{ padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '14px', fontWeight: '700', color: '#F3F4F6' }}>채팅</span>
              </div>

              <div className="custom-scrollbar" style={{ flex: 1, padding: '20px', overflowY: 'auto' }}>
                {/* Notice Box */}
                <div style={{ backgroundColor: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.2)', borderRadius: '12px', padding: '16px', position: 'relative' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#F87171', fontSize: '13px', fontWeight: '700', marginBottom: '8px' }}>
                    <AlertTriangle size={16} /> 서비스 이용 안내
                  </div>
                  <div style={{ color: '#FCA5A5', fontSize: '12px', lineHeight: '1.6', wordBreak: 'keep-all' }}>
                    불건전한 행동이나 욕설 발견 시 즉각 강제 퇴장 및 계정 정지 조치가 이루어질 수 있습니다. 모두가 집중할 수 있는 분위기를 만들어주세요.
                  </div>
                </div>
              </div>

              {/* Chat Input */}
              <div style={{ padding: '20px', backgroundColor: '#0F172A', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                <div style={{ display: 'flex', alignItems: 'center', backgroundColor: '#1E293B', borderRadius: '24px', padding: '8px 16px', border: '1px solid rgba(255,255,255,0.1)' }}>
                  <div style={{ fontSize: '13px', color: '#9CA3AF', paddingRight: '12px', borderRight: '1px solid rgba(255,255,255,0.1)', marginRight: '12px', display: 'flex', alignItems: 'center', gap: '6px', height: '20px', whiteSpace: 'nowrap' }}>
                    전체 <span style={{ fontSize: '8px', opacity: 0.8 }}>▼</span>
                  </div>
                  <input
                    type="text"
                    placeholder="메시지 입력..."
                    style={{ flex: 1, border: 'none', outline: 'none', fontSize: '13px', color: '#F3F4F6', backgroundColor: 'transparent', height: '20px', lineHeight: '20px', padding: 0, margin: 0 }}
                  />
                  <button style={{ background: 'linear-gradient(135deg, #22C55E, #16A34A)', border: 'none', width: '32px', height: '32px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', marginLeft: '8px', boxShadow: '0 2px 8px rgba(34, 197, 94, 0.3)' }}>
                    <Send size={14} color="white" style={{ marginLeft: '-2px', marginTop: '2px' }} />
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

      </div>

      {/* 장치 설정 모달 */}
      {showSettings && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100000 }}>
          <div style={{ backgroundColor: '#1E293B', borderRadius: '16px', width: '480px', padding: '32px', border: '1px solid rgba(255,255,255,0.1)', boxShadow: '0 20px 40px rgba(0,0,0,0.5)', display: 'flex', flexDirection: 'column', gap: '24px', animation: 'slideUp 0.3s ease-out' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h2 style={{ margin: 0, fontSize: '18px', fontWeight: '700', color: '#F3F4F6' }}>장치 설정</h2>
              <X size={20} color="#9CA3AF" cursor="pointer" onClick={() => setShowSettings(false)} />
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              {/* 카메라 설정 */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#9CA3AF', marginBottom: '8px' }}>
                  <Video size={16} /> <span style={{ fontSize: '14px', fontWeight: '600' }}>카메라</span>
                </div>
                <div style={{ backgroundColor: '#0F172A', borderRadius: '12px', padding: '12px', border: '1px solid rgba(255,255,255,0.05)' }}>
                  <select style={{ width: '100%', backgroundColor: 'transparent', border: 'none', outline: 'none', color: '#F3F4F6', fontSize: '14px', cursor: 'pointer' }}>
                    <option value="cam1" style={{ backgroundColor: '#1E293B' }}>기본 카메라 (FaceTime HD Camera)</option>
                    <option value="cam2" style={{ backgroundColor: '#1E293B' }}>OBS Virtual Camera</option>
                  </select>
                </div>
                <div style={{ fontSize: '12px', color: '#34D399', marginTop: '6px', marginLeft: '4px' }}>정상적으로 작동중입니다</div>
              </div>

              {/* 마이크 설정 */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#9CA3AF', marginBottom: '8px' }}>
                  <Mic size={16} /> <span style={{ fontSize: '14px', fontWeight: '600' }}>마이크</span>
                </div>
                <div style={{ backgroundColor: '#0F172A', borderRadius: '12px', padding: '12px', border: '1px solid rgba(255,255,255,0.05)' }}>
                  <select style={{ width: '100%', backgroundColor: 'transparent', border: 'none', outline: 'none', color: '#F3F4F6', fontSize: '14px', cursor: 'pointer' }}>
                    <option value="mic1" style={{ backgroundColor: '#1E293B' }}>기본 마이크 (Built-in Microphone)</option>
                  </select>
                </div>
                <div style={{ fontSize: '12px', color: '#34D399', marginTop: '6px', marginLeft: '4px' }}>정상적으로 작동중입니다</div>
              </div>

              {/* 스피커 설정 */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#9CA3AF', marginBottom: '8px' }}>
                  <Volume2 size={16} /> <span style={{ fontSize: '14px', fontWeight: '600' }}>스피커</span>
                </div>
                <div style={{ backgroundColor: '#0F172A', borderRadius: '12px', padding: '12px', border: '1px solid rgba(255,255,255,0.05)' }}>
                  <select style={{ width: '100%', backgroundColor: 'transparent', border: 'none', outline: 'none', color: '#F3F4F6', fontSize: '14px', cursor: 'pointer' }}>
                    <option value="spk1" style={{ backgroundColor: '#1E293B' }}>시스템 기본값 (Built-in Output)</option>
                  </select>
                </div>
                <div style={{ fontSize: '12px', color: '#34D399', marginTop: '6px', marginLeft: '4px' }}>정상적으로 작동중입니다</div>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '8px' }}>
              <button
                style={{ padding: '8px 24px', backgroundColor: '#3B82F6', color: 'white', borderRadius: '8px', border: 'none', fontWeight: '600', cursor: 'pointer', boxShadow: '0 4px 12px rgba(59,130,246,0.3)' }}
                onClick={() => setShowSettings(false)}
              >
                확인
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 통계/멤버 모달 */}
      {showStatsModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100000 }}>
          <div style={{ backgroundColor: '#0F172A', borderRadius: '16px', width: '800px', maxWidth: '90vw', height: '600px', border: '1px solid rgba(255,255,255,0.1)', boxShadow: '0 20px 40px rgba(0,0,0,0.5)', display: 'flex', flexDirection: 'column', overflow: 'hidden', animation: 'slideUp 0.3s ease-out' }}>

            {/* Header Tabs */}
            <div style={{ display: 'flex', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.05)', backgroundColor: '#1E293B' }}>
              <div style={{ padding: '16px 32px', borderBottom: '2px solid #3B82F6', color: '#F3F4F6', fontWeight: '700', fontSize: '15px' }}>
                멤버 (학습통계)
              </div>
              <div style={{ flex: 1 }} />
              <div style={{ padding: '0 20px', cursor: 'pointer' }} onClick={() => setShowStatsModal(false)}>
                <X size={20} color="#9CA3AF" />
              </div>
            </div>

            {/* Content Area */}
            <div className="custom-scrollbar" style={{ flex: 1, padding: '0', overflowY: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', color: '#9CA3AF', fontSize: '13px' }}>
                    <th style={{ padding: '16px 32px', fontWeight: '500' }}>이름</th>
                    <th style={{ padding: '16px 16px', fontWeight: '500' }}>최근 출석시간</th>
                    <th style={{ padding: '16px 16px', fontWeight: '500' }}>일주일 출석시간</th>
                    <th style={{ padding: '16px 32px', fontWeight: '500' }}>평균 출석시간</th>
                  </tr>
                </thead>
                <tbody>
                  <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.02)', backgroundColor: 'rgba(255,255,255,0.02)' }}>
                    <td style={{ padding: '16px 32px', color: '#60A5FA', fontWeight: '600', fontSize: '14px' }}>mindcontrol (나)</td>
                    <td style={{ padding: '16px 16px', color: '#E5E7EB', fontSize: '14px' }}>오늘 09:30</td>
                    <td style={{ padding: '16px 16px', color: '#E5E7EB', fontSize: '14px' }}>32시간 15분</td>
                    <td style={{ padding: '16px 32px', color: '#E5E7EB', fontSize: '14px' }}>4시간 30분</td>
                  </tr>
                  <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.02)' }}>
                    <td style={{ padding: '16px 32px', color: '#3B82F6', fontWeight: '600', fontSize: '14px' }}>잠재용</td>
                    <td style={{ padding: '16px 16px', color: '#9CA3AF', fontSize: '14px' }}>어제 22:10</td>
                    <td style={{ padding: '16px 16px', color: '#E5E7EB', fontSize: '14px' }}>14시간 50분</td>
                    <td style={{ padding: '16px 32px', color: '#E5E7EB', fontSize: '14px' }}>2시간 10분</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* 방 관리 (설정) 모달 */}
      {showRoomManageModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100000 }}>
          <div style={{ backgroundColor: '#0F172A', borderRadius: '16px', width: '800px', maxWidth: '90vw', height: '720px', maxHeight: '90vh', border: '1px solid rgba(255,255,255,0.1)', boxShadow: '0 20px 40px rgba(0,0,0,0.5)', display: 'flex', flexDirection: 'column', overflow: 'hidden', animation: 'slideUp 0.3s ease-out' }}>

            {/* Header Tabs */}
            <div style={{ display: 'flex', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.05)', backgroundColor: '#1E293B', padding: '0 8px' }}>
              <div
                style={{ padding: '16px 24px', borderBottom: roomManageTab === 'settings' ? '2px solid #3B82F6' : '2px solid transparent', color: roomManageTab === 'settings' ? '#F3F4F6' : '#9CA3AF', fontWeight: '700', fontSize: '15px', cursor: 'pointer', transition: '0.2s' }}
                onClick={() => setRoomManageTab('settings')}
              >
                방 관리 (설정)
              </div>
              <div
                style={{ padding: '16px 24px', borderBottom: roomManageTab === 'members' ? '2px solid #3B82F6' : '2px solid transparent', color: roomManageTab === 'members' ? '#F3F4F6' : '#9CA3AF', fontWeight: '700', fontSize: '15px', cursor: 'pointer', transition: '0.2s' }}
                onClick={() => setRoomManageTab('members')}
              >
                멤버 관리
              </div>
              {study?.isPrivate && (
                <div
                  style={{ padding: '16px 24px', borderBottom: roomManageTab === 'applications' ? '2px solid #3B82F6' : '2px solid transparent', color: roomManageTab === 'applications' ? '#F3F4F6' : '#9CA3AF', fontWeight: '700', fontSize: '15px', cursor: 'pointer', transition: '0.2s', display: 'flex', alignItems: 'center', gap: '6px' }}
                  onClick={() => setRoomManageTab('applications')}
                >
                  가입 신청 관리 <span style={{ backgroundColor: '#EF4444', color: 'white', fontSize: '11px', padding: '2px 6px', borderRadius: '10px' }}>2</span>
                </div>
              )}
              <div style={{ flex: 1 }} />
              <div style={{ padding: '0 20px', cursor: 'pointer' }} onClick={() => setShowRoomManageModal(false)}>
                <X size={20} color="#9CA3AF" />
              </div>
            </div>

            {/* Content Area */}
            <div className="custom-scrollbar" style={{ flex: 1, padding: '24px 32px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '24px' }}>

              {roomManageTab === 'settings' ? (
                <>
                  {/* 해시태그 */}
                  <div style={{ display: 'flex', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '24px' }}>
                    <div style={{ width: '160px', color: '#E5E7EB', fontWeight: '600', fontSize: '14px', paddingTop: '8px' }}>해시태그</div>
                    <div style={{ flex: 1, paddingRight: '4px' }}>
                      <input type="text" placeholder="스터디를 대표하는 키워드를 입력하세요. (최대 3개)" style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none' }} />
                    </div>
                  </div>

                  {/* 기간 */}
                  <div style={{ display: 'flex', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '24px' }}>
                    <div style={{ width: '160px', color: '#E5E7EB', fontWeight: '600', fontSize: '14px', paddingTop: '8px' }}>기간</div>
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '12px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <div style={{ backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '8px 16px', color: '#F3F4F6', fontSize: '14px' }}>2021.11.22</div>
                        <span style={{ color: '#9CA3AF' }}>~</span>
                        <div style={{ backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '8px 16px', color: '#F3F4F6', fontSize: '14px' }}>2027.04.06</div>
                      </div>
                      <div style={{ backgroundColor: 'rgba(245, 158, 11, 0.1)', color: '#F59E0B', padding: '4px 12px', borderRadius: '4px', fontSize: '13px', fontWeight: '700', width: 'fit-content' }}>총 1961 일</div>
                    </div>
                  </div>

                  {/* 목표시간 */}
                  <div style={{ display: 'flex', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '24px' }}>
                    <div style={{ width: '160px', color: '#E5E7EB', fontWeight: '600', fontSize: '14px', paddingTop: '8px' }}>목표시간</div>
                    <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <select style={{ backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '8px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none' }}>
                        <option>매일</option>
                      </select>
                      <input type="number" defaultValue={1} style={{ width: '80px', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '8px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none' }} />
                    </div>
                  </div>


                  {/* 초기 장치 설정 */}
                  <div style={{ display: 'flex', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '24px' }}>
                    <div style={{ width: '160px', color: '#E5E7EB', fontWeight: '600', fontSize: '14px', paddingTop: '4px' }}>초기 장치 설정</div>
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#F3F4F6', fontSize: '14px' }}>
                          카메라 <div style={{ width: '36px', height: '20px', backgroundColor: '#22C55E', borderRadius: '10px', position: 'relative' }}><div style={{ width: '16px', height: '16px', backgroundColor: 'white', borderRadius: '50%', position: 'absolute', right: '2px', top: '2px' }} /></div>
                        </label>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#F3F4F6', fontSize: '14px' }}>
                          마이크 <div style={{ width: '36px', height: '20px', backgroundColor: '#4B5563', borderRadius: '10px', position: 'relative' }}><div style={{ width: '16px', height: '16px', backgroundColor: 'white', borderRadius: '50%', position: 'absolute', left: '2px', top: '2px' }} /></div>
                        </label>
                      </div>
                      <div style={{ fontSize: '12px', color: '#9CA3AF' }}>* 입장하는 인원들의 초기장치를 제어합니다.</div>
                    </div>
                  </div>

                  {/* 스터디 공지사항 */}
                  <div style={{ display: 'flex' }}>
                    <div style={{ width: '160px', color: '#E5E7EB', fontWeight: '600', fontSize: '14px', paddingTop: '8px' }}>스터디 공지사항</div>
                    <div style={{ flex: 1, paddingRight: '4px' }}>
                      <textarea
                        className="custom-scrollbar"
                        defaultValue="자격증 자율 스터디입니다.&#10;누구나 함께 공부하며 스터디 친구를 사귈 수 있습니다.&#10;&#10;해당 스터디룸은 StudyBridge에서 개설한 스터디룸으로,&#10;입장한 지 3일 이상 경과된 상황에서 카메라 송출이 되고 있지 않는다면 발견되는 즉시 무통보 강제 퇴장 조치..."
                        style={{ width: '100%', boxSizing: 'border-box', height: '120px', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none', resize: 'none', lineHeight: '1.6' }}
                      />
                    </div>
                  </div>
                </>
              ) : roomManageTab === 'members' ? (
                <div style={{ width: '100%', overflowX: 'auto', padding: '8px 0' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', color: '#9CA3AF', fontSize: '13px', fontWeight: '500' }}>
                        <th style={{ padding: '12px 16px', fontWeight: '500' }}>이름</th>
                        <th style={{ padding: '12px 16px', fontWeight: '500' }}>최근 출석시간</th>
                        <th style={{ padding: '12px 16px', fontWeight: '500' }}>최근 공부시간</th>
                        <th style={{ padding: '12px 16px', fontWeight: '500' }}>누적 공부시간</th>
                        <th style={{ padding: '12px 16px', fontWeight: '500' }}></th>
                      </tr>
                    </thead>
                    <tbody>
                      {/* 방장 */}
                      <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.02)' }}>
                        <td style={{ padding: '16px' }}>
                          <div style={{ color: '#3B82F6', fontWeight: '600', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: '#3B82F6', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px' }}>M</div>
                            mindcontrol (나)
                          </div>
                        </td>
                        <td style={{ padding: '16px', color: '#E5E7EB', fontSize: '14px' }}>오늘 09:30</td>
                        <td style={{ padding: '16px', color: '#E5E7EB', fontSize: '14px' }}>1시간 20분</td>
                        <td style={{ padding: '16px', color: '#E5E7EB', fontSize: '14px' }}>32시간 15분</td>
                        <td style={{ padding: '16px', color: '#9CA3AF', fontSize: '13px', fontWeight: '500', textAlign: 'right' }}>방장</td>
                      </tr>
                      {/* 일반 멤버 */}
                      <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.02)' }}>
                        <td style={{ padding: '16px' }}>
                          <div style={{ color: '#F3F4F6', fontWeight: '500', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: '#6366F1', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px' }}>잠</div>
                            잠재용
                          </div>
                        </td>
                        <td style={{ padding: '16px', color: '#E5E7EB', fontSize: '14px' }}>어제 22:10</td>
                        <td style={{ padding: '16px', color: '#E5E7EB', fontSize: '14px' }}>0시간</td>
                        <td style={{ padding: '16px', color: '#E5E7EB', fontSize: '14px' }}>14시간 50분</td>
                        <td style={{ padding: '16px', textAlign: 'right' }}>
                          <button style={{ padding: '6px 12px', backgroundColor: 'rgba(239,68,68,0.1)', color: '#EF4444', borderRadius: '6px', border: '1px solid rgba(239,68,68,0.2)', fontSize: '12px', fontWeight: '600', cursor: 'pointer', transition: '0.2s' }} onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'rgba(239,68,68,0.2)'; }} onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'rgba(239,68,68,0.1)'; }}>
                            강제 퇴장
                          </button>
                        </td>
                      </tr>
                      {/* AI 에이전트 */}
                      <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.02)' }}>
                        <td style={{ padding: '16px' }}>
                          <div style={{ color: '#F3F4F6', fontWeight: '500', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: '#10B981', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px' }}>S</div>
                            StudyMate
                          </div>
                        </td>
                        <td style={{ padding: '16px', color: '#9CA3AF', fontSize: '14px' }}>-</td>
                        <td style={{ padding: '16px', color: '#9CA3AF', fontSize: '14px' }}>-</td>
                        <td style={{ padding: '16px', color: '#9CA3AF', fontSize: '14px' }}>-</td>
                        <td style={{ padding: '16px', textAlign: 'right' }}>
                          <button style={{ padding: '6px 12px', backgroundColor: 'rgba(239,68,68,0.1)', color: '#EF4444', borderRadius: '6px', border: '1px solid rgba(239,68,68,0.2)', fontSize: '12px', fontWeight: '600', cursor: 'pointer', transition: '0.2s' }} onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'rgba(239,68,68,0.2)'; }} onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'rgba(239,68,68,0.1)'; }}>
                            강제 퇴장
                          </button>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              ) : (
                <div style={{ width: '100%', overflowX: 'auto', padding: '8px 0' }}>
                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '16px' }}>
                    <button
                      style={{ padding: '8px 16px', backgroundColor: '#22C55E', color: 'white', borderRadius: '8px', border: 'none', fontWeight: '600', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', transition: '0.2s', boxShadow: '0 4px 12px rgba(34,197,94,0.3)' }}
                      onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#16A34A'}
                      onMouseLeave={(e) => e.currentTarget.style.backgroundColor = '#22C55E'}
                      onClick={() => {
                        showPrompt('멤버 초대', '초대할 사용자의 이메일을 입력하세요:', '예: user@example.com', (email) => {
                          if (email) {
                            if (email.includes('@')) {
                              showAlert('초대 완료', `${email} 님에게 스터디 초대장을 발송했습니다!`);
                            } else {
                              showAlert('오류', '올바른 이메일 형식이 아닙니다.');
                            }
                          }
                        });
                      }}
                    >
                      <UserPlus size={14} /> 멤버 초대하기
                    </button>
                  </div>
                  <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', color: '#9CA3AF', fontSize: '13px', fontWeight: '500' }}>
                        <th style={{ padding: '12px 16px', fontWeight: '500', width: '20%' }}>신청자</th>
                        <th style={{ padding: '12px 16px', fontWeight: '500', width: '50%' }}>신청 메시지</th>
                        <th style={{ padding: '12px 16px', fontWeight: '500', width: '15%' }}>신청일</th>
                        <th style={{ padding: '12px 16px', fontWeight: '500', width: '15%', textAlign: 'center' }}>관리</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.02)' }}>
                        <td style={{ padding: '16px' }}>
                          <div style={{ color: '#F3F4F6', fontWeight: '500', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <div style={{ width: '28px', height: '28px', borderRadius: '50%', backgroundColor: '#8B5CF6', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '13px' }}>합</div>
                            합격기원1일차
                          </div>
                        </td>
                        <td style={{ padding: '16px', color: '#E5E7EB', fontSize: '13px', lineHeight: '1.5' }}>
                          안녕하세요! 매일 아침 9시부터 밤 11시까지 풀타임으로 공부할 예정입니다. 절대 지각 결석 안 합니다! 꼭 받아주세요.
                        </td>
                        <td style={{ padding: '16px', color: '#9CA3AF', fontSize: '13px' }}>오늘 14:30</td>
                        <td style={{ padding: '16px', textAlign: 'center' }}>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
                            <button onClick={() => showAlert('알림', '승인되었습니다.')} style={{ width: '32px', height: '32px', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(34,197,94,0.1)', color: '#22C55E', borderRadius: '6px', border: '1px solid rgba(34,197,94,0.2)', cursor: 'pointer', transition: '0.2s' }} onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(34,197,94,0.2)'} onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'rgba(34,197,94,0.1)'} title="승인">
                              <Check size={16} />
                            </button>
                            <button onClick={() => showAlert('알림', '거절되었습니다.')} style={{ width: '32px', height: '32px', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(239,68,68,0.1)', color: '#EF4444', borderRadius: '6px', border: '1px solid rgba(239,68,68,0.2)', cursor: 'pointer', transition: '0.2s' }} onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(239,68,68,0.2)'} onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'rgba(239,68,68,0.1)'} title="거절">
                              <X size={16} />
                            </button>
                          </div>
                        </td>
                      </tr>
                      <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.02)' }}>
                        <td style={{ padding: '16px' }}>
                          <div style={{ color: '#F3F4F6', fontWeight: '500', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <div style={{ width: '28px', height: '28px', borderRadius: '50%', backgroundColor: '#F59E0B', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '13px' }}>P</div>
                            PythonMaster
                          </div>
                        </td>
                        <td style={{ padding: '16px', color: '#9CA3AF', fontSize: '13px', fontStyle: 'italic' }}>
                          (메시지 없음)
                        </td>
                        <td style={{ padding: '16px', color: '#9CA3AF', fontSize: '13px' }}>어제 22:15</td>
                        <td style={{ padding: '16px', textAlign: 'center' }}>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
                            <button onClick={() => showAlert('알림', '승인되었습니다.')} style={{ width: '32px', height: '32px', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(34,197,94,0.1)', color: '#22C55E', borderRadius: '6px', border: '1px solid rgba(34,197,94,0.2)', cursor: 'pointer', transition: '0.2s' }} onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(34,197,94,0.2)'} onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'rgba(34,197,94,0.1)'} title="승인">
                              <Check size={16} />
                            </button>
                            <button onClick={() => showAlert('알림', '거절되었습니다.')} style={{ width: '32px', height: '32px', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(239,68,68,0.1)', color: '#EF4444', borderRadius: '6px', border: '1px solid rgba(239,68,68,0.2)', cursor: 'pointer', transition: '0.2s' }} onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(239,68,68,0.2)'} onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'rgba(239,68,68,0.1)'} title="거절">
                              <X size={16} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Save Button */}
            <div style={{ padding: '24px 32px', display: 'flex', justifyContent: 'flex-end', backgroundColor: '#0F172A', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
              <button
                style={{ padding: '8px 24px', backgroundColor: '#22C55E', color: 'white', borderRadius: '8px', border: 'none', fontWeight: '600', cursor: 'pointer', boxShadow: '0 4px 12px rgba(34,197,94,0.3)', transition: '0.2s' }}
                onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#16A34A'}
                onMouseLeave={(e) => e.currentTarget.style.backgroundColor = '#22C55E'}
                onClick={() => setShowRoomManageModal(false)}
              >
                닫기
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 관리자 신고/문의 관리 모달 */}
      {showAdminReportModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100000 }}>
          <div style={{ backgroundColor: '#0F172A', borderRadius: '16px', width: '800px', maxWidth: '90vw', height: 'auto', maxHeight: '90vh', border: '1px solid rgba(255,255,255,0.1)', boxShadow: '0 20px 40px rgba(0,0,0,0.5)', display: 'flex', flexDirection: 'column', overflow: 'hidden', animation: 'slideUp 0.3s ease-out' }}>

            {/* Header Tabs */}
            <div style={{ display: 'flex', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.05)', backgroundColor: '#1E293B', padding: '0 8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '16px 24px', color: '#60A5FA', fontWeight: '700', fontSize: '15px' }}>
                <MessageSquare size={18} />
                문의 및 신고하기
              </div>
              <div style={{ width: '1px', height: '20px', backgroundColor: 'rgba(255,255,255,0.1)', margin: '0 16px' }} />
              <div
                style={{ padding: '16px 24px', borderBottom: adminReportTab === 'inquiry' ? '2px solid #60A5FA' : '2px solid transparent', color: adminReportTab === 'inquiry' ? '#F3F4F6' : '#9CA3AF', fontWeight: '700', fontSize: '15px', cursor: 'pointer', transition: '0.2s' }}
                onClick={() => setAdminReportTab('inquiry')}
              >
                1:1 문의
              </div>
              <div
                style={{ padding: '16px 24px', borderBottom: adminReportTab === 'report' ? '2px solid #EF4444' : '2px solid transparent', color: adminReportTab === 'report' ? '#F3F4F6' : '#9CA3AF', fontWeight: '700', fontSize: '15px', cursor: 'pointer', transition: '0.2s' }}
                onClick={() => setAdminReportTab('report')}
              >
                유저 신고
              </div>
              <div style={{ flex: 1 }} />
              <div style={{ padding: '0 20px', cursor: 'pointer' }} onClick={() => setShowAdminReportModal(false)}>
                <X size={20} color="#9CA3AF" />
              </div>
            </div>

            {/* Content Area */}
            <div className="custom-scrollbar" style={{ flex: 1, padding: '32px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '24px' }}>
              {adminReportTab === 'inquiry' ? (
                <>
                  {/* 문의 카테고리 */}
                  <div>
                    <div style={{ color: '#E5E7EB', fontWeight: '600', fontSize: '14px', marginBottom: '12px' }}>문의 유형</div>
                    <select style={{ width: '100%', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none', cursor: 'pointer' }}>
                      <option>이용 문의</option>
                      <option>버그 및 오류 신고</option>
                      <option>기타</option>
                    </select>
                  </div>

                  {/* 제목 */}
                  <div>
                    <div style={{ color: '#E5E7EB', fontWeight: '600', fontSize: '14px', marginBottom: '12px' }}>제목</div>
                    <input type="text" placeholder="문의 제목을 입력하세요." style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none' }} />
                  </div>

                  {/* 내용 */}
                  <div>
                    <div style={{ color: '#E5E7EB', fontWeight: '600', fontSize: '14px', marginBottom: '12px' }}>문의 내용</div>
                    <textarea placeholder="문의하실 내용을 상세히 적어주세요.&#13;&#10;최대한 빠르고 정확하게 답변해 드리겠습니다." style={{ width: '100%', boxSizing: 'border-box', height: '160px', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none', resize: 'none', lineHeight: '1.6' }} />
                  </div>
                </>
              ) : (
                <>
                  {/* 신고 대상 */}
                  <div>
                    <div style={{ color: '#EF4444', fontWeight: '600', fontSize: '14px', marginBottom: '12px' }}>신고할 유저</div>
                    <select style={{ width: '100%', backgroundColor: '#1E293B', border: '1px solid rgba(239,68,68,0.2)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none', cursor: 'pointer' }}>
                      <option value="">신고할 멤버를 선택하세요</option>
                      <option value="user1">잠재용</option>
                      <option value="user2">StudyMate (AI 에이전트)</option>
                    </select>
                  </div>

                  {/* 신고 사유 */}
                  <div>
                    <div style={{ color: '#E5E7EB', fontWeight: '600', fontSize: '14px', marginBottom: '12px' }}>신고 사유</div>
                    <select style={{ width: '100%', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none', cursor: 'pointer' }}>
                      <option>욕설 / 비방 / 혐오 발언</option>
                      <option>도배 및 스팸</option>
                      <option>부적절한 프로필 또는 닉네임</option>
                      <option>기타 (직접 작성)</option>
                    </select>
                  </div>

                  {/* 내용 */}
                  <div>
                    <div style={{ color: '#E5E7EB', fontWeight: '600', fontSize: '14px', marginBottom: '12px' }}>상세 사유</div>
                    <textarea placeholder="신고 사유를 상세히 적어주세요.&#13;&#10;허위 신고 시 서비스 이용에 불이익을 받을 수 있습니다." style={{ width: '100%', boxSizing: 'border-box', height: '160px', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none', resize: 'none', lineHeight: '1.6' }} />
                  </div>
                </>
              )}
            </div>

            {/* Submit Button Area */}
            <div style={{ padding: '24px 32px', display: 'flex', justifyContent: 'flex-end', gap: '12px', backgroundColor: '#0F172A', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
              <button
                style={{ padding: '10px 24px', backgroundColor: 'transparent', color: '#9CA3AF', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)', fontWeight: '600', cursor: 'pointer', transition: '0.2s' }}
                onClick={() => setShowAdminReportModal(false)}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'; e.currentTarget.style.color = '#F3F4F6'; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; e.currentTarget.style.color = '#9CA3AF'; }}
              >
                취소
              </button>
              <button
                style={{ padding: '10px 24px', backgroundColor: adminReportTab === 'inquiry' ? '#22C55E' : '#EF4444', color: 'white', borderRadius: '8px', border: 'none', fontWeight: '600', cursor: 'pointer', boxShadow: adminReportTab === 'inquiry' ? '0 4px 12px rgba(34,197,94,0.3)' : '0 4px 12px rgba(239,68,68,0.3)', transition: '0.2s' }}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = adminReportTab === 'inquiry' ? '#16A34A' : '#DC2626'; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = adminReportTab === 'inquiry' ? '#22C55E' : '#EF4444'; }}
                onClick={() => setShowAdminReportModal(false)}
              >
                {adminReportTab === 'inquiry' ? '문의 접수하기' : '신고 접수하기'}
              </button>
            </div>
          </div>
        </div>
      )}
      {/* 커스텀 모달 UI */}
      {customAlert.isOpen && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 100000, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(0,0,0,0.4)', backdropFilter: 'blur(2px)' }}>
          <div style={{ backgroundColor: '#ffffff', borderRadius: '12px', padding: '24px 24px 20px', width: '320px', boxShadow: '0 4px 20px rgba(0,0,0,0.15)', animation: 'fadeIn 0.2s ease-out' }}>
            <h3 style={{ margin: '0 0 12px 0', fontSize: '16px', fontWeight: '700', color: '#111827', textAlign: 'center' }}>{customAlert.title || '알림'}</h3>
            <p style={{ margin: '0 0 20px 0', fontSize: '14px', color: '#4B5563', lineHeight: '1.5', whiteSpace: 'pre-wrap', textAlign: 'center' }}>{customAlert.message}</p>

            {customAlert.type === 'prompt' && (
              <input
                autoFocus
                type="text"
                placeholder={customAlert.inputPlaceholder}
                value={customAlert.inputValue}
                onChange={(e) => setCustomAlert(prev => ({ ...prev, inputValue: e.target.value }))}
                onKeyDown={(e) => e.key === 'Enter' && customAlert.onConfirm(customAlert.inputValue)}
                style={{ width: '100%', boxSizing: 'border-box', padding: '10px 12px', borderRadius: '8px', border: '1px solid #D1D5DB', backgroundColor: '#F9FAFB', color: '#111827', marginBottom: '24px', outline: 'none', fontSize: '14px' }}
              />
            )}

            <div style={{ display: 'flex', justifyContent: 'center', gap: '8px' }}>
              {(customAlert.type === 'confirm' || customAlert.type === 'prompt') && (
                <button
                  style={{ flex: 1, padding: '10px 0', backgroundColor: '#F3F4F6', color: '#4B5563', border: '1px solid #E5E7EB', borderRadius: '8px', cursor: 'pointer', fontWeight: '600', fontSize: '14px' }}
                  onClick={customAlert.onCancel}
                >
                  취소
                </button>
              )}
              <button
                style={{ flex: 1, padding: '10px 0', backgroundColor: '#22C55E', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: '600', fontSize: '14px' }}
                onClick={() => customAlert.type === 'prompt' ? customAlert.onConfirm(customAlert.inputValue) : customAlert.onConfirm()}
              >
                확인
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
