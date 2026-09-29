import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { materialService } from '../services/api';
import { UploadCloud, FileText, CheckCircle, AlertCircle, Clock, ExternalLink } from 'lucide-react';

export default function Materials() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [materials, setMaterials] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef(null);

  const fetchMaterials = async () => {
    if (!user) return;
    try {
      setIsLoading(true);
      const data = await materialService.getMaterials();
      setMaterials(Array.isArray(data) ? data : []);
    } catch (error) {
      console.error('자료 조회 실패:', error);
      setMaterials([]);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (user) {
      fetchMaterials();
    } else {
      setIsLoading(false);
      setMaterials([]);
    }
  }, [user]);

  const checkAuth = (e) => {
    if (!user) {
      if (e) e.preventDefault();
      alert('로그인이 필요한 기능입니다. 로그인 페이지로 이동합니다.');
      navigate('/login');
      return false;
    }
    return true;
  };

  const handleFileChange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const allowedTypes = [
      'application/pdf',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'text/plain',
    ];
    const lowerName = file.name.toLowerCase();
    const allowedByExtension = lowerName.endsWith('.pdf') || lowerName.endsWith('.docx') || lowerName.endsWith('.txt');
    if (!allowedTypes.includes(file.type) && !allowedByExtension) {
      alert('문서 파일만 업로드 가능합니다. (PDF/DOCX/TXT)');
      return;
    }

    if (file.size > 50 * 1024 * 1024) {
      alert('파일 크기는 50MB를 초과할 수 없습니다.');
      return;
    }

    try {
      setIsUploading(true);
      await materialService.uploadMaterial(file);
      alert('파일 업로드가 완료되었습니다.');
      fetchMaterials();
    } catch (error) {
      console.error('업로드 실패:', error);
      alert(error.message || '파일 업로드 중 오류가 발생했습니다. (백엔드 API 미구현일 수 있습니다)');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleDownload = async (materialId) => {
    if (!checkAuth()) return;
    try {
      const data = await materialService.getMaterialDetail(materialId);
      if (data && data.s3PresignedUrl) {
        window.open(data.s3PresignedUrl, '_blank');
      } else {
        alert('다운로드 URL을 가져오지 못했습니다.');
      }
    } catch (error) {
      console.error('상세 조회 실패:', error);
      alert(error.message || '자료 정보 조회에 실패했습니다.');
    }
  };

  const formatFileSize = (bytes) => {
    if (!bytes || bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const renderStatusBadge = (status) => {
    switch (status) {
      case 'SUCCESS':
        return (
            <span className="badge recruiting" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <CheckCircle size={14} /> 추출 완료
          </span>
        );
      case 'PENDING':
        return (
            <span className="badge" style={{ backgroundColor: '#FEF3C7', color: '#D97706', display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Clock size={14} /> 처리 중
          </span>
        );
      case 'FAILED':
        return (
            <span className="badge" style={{ backgroundColor: '#FEE2E2', color: '#DC2626', display: 'flex', alignItems: 'center', gap: '4px' }}>
            <AlertCircle size={14} /> 실패
          </span>
        );
      default:
        return null;
    }
  };

  return (
      <div className="container-main">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
          <div>
            <h2>내 자료보관함</h2>
            <p style={{ color: 'var(--color-text-muted)', marginTop: '-8px' }}>
              학습에 필요한 문서(PDF/DOCX/TXT)를 등록하고 관리하세요.
            </p>
          </div>
          <div>
            <input
                type="file"
                accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
                ref={fileInputRef}
                style={{ display: 'none' }}
                onChange={handleFileChange}
            />
            <button
                className="btn-primary"
                onClick={(e) => {
                  if (checkAuth(e)) fileInputRef.current?.click();
                }}
                disabled={isUploading}
                style={{ width: 'auto', padding: '0 20px' }}
            >
              <UploadCloud size={18} />
              {isUploading ? '업로드 중...' : '새 자료 업로드'}
            </button>
            <p style={{ margin: '8px 0 0', color: 'var(--color-text-muted)', fontSize: '13px' }}>
              PDF, DOCX, TXT 파일을 지원합니다.
            </p>
          </div>
        </div>

        {isUploading && (
            <div className="glass-panel" style={{ marginBottom: '24px', textAlign: 'center', padding: '30px' }}>
              <UploadCloud size={40} color="var(--color-primary)" style={{ animation: 'bounce 2s infinite' }} />
              <h3 style={{ marginTop: '16px', color: 'var(--color-text-main)' }}>문서 업로드 및 분석 중...</h3>
              <p style={{ color: 'var(--color-text-muted)' }}>파일 크기에 따라 약간의 시간이 소요될 수 있습니다.</p>
            </div>
        )}

        <div className="glass-panel animate-fade-in" style={{ padding: '24px', minHeight: '400px' }}>
          {isLoading ? (
              <div style={{ textAlign: 'center', padding: '40px', color: 'var(--color-text-muted)' }}>
                로딩 중...
              </div>
          ) : materials.length === 0 ? (
              <div className="empty-state" style={{ padding: '60px 0' }}>
                <FileText size={48} style={{ color: 'var(--color-border)', marginBottom: '16px' }} />
                <h3 style={{ margin: '0 0 8px 0', color: 'var(--color-text-main)' }}>등록된 자료가 없습니다</h3>
                <p style={{ margin: 0 }}>첫 번째 문서(PDF/DOCX/TXT)를 업로드해 보세요.</p>
              </div>
          ) : (
              <div style={{ display: 'grid', gap: '16px', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}>
                {materials.map((mat) => (
                    <div
                        key={mat.materialId}
                        style={{
                          border: '1px solid var(--color-border)',
                          borderRadius: '12px',
                          padding: '20px',
                          backgroundColor: 'var(--color-bg-card)',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '12px',
                          transition: 'transform 0.2s, box-shadow 0.2s',
                          cursor: 'pointer'
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.transform = 'translateY(-2px)';
                          e.currentTarget.style.boxShadow = 'var(--shadow-card)';
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.transform = 'none';
                          e.currentTarget.style.boxShadow = 'none';
                        }}
                        onClick={() => handleDownload(mat.materialId)}
                    >
                      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
                        <div style={{
                          width: '40px', height: '40px', borderRadius: '8px',
                          backgroundColor: 'rgba(96, 201, 90, 0.1)', color: 'var(--color-primary)',
                          display: 'flex', justifyContent: 'center', alignItems: 'center', flexShrink: 0
                        }}>
                          <FileText size={20} />
                        </div>
                        <div style={{ flex: 1, overflow: 'hidden' }}>
                          <h4 style={{ margin: '0 0 4px 0', fontSize: '15px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {mat.originalFileName}
                          </h4>
                          <p style={{ margin: 0, fontSize: '12px', color: 'var(--color-text-muted)' }}>
                            {new Date(mat.uploadedAt).toLocaleDateString()} • {formatFileSize(mat.fileSize)}
                          </p>
                        </div>
                      </div>

                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 'auto', paddingTop: '12px', borderTop: '1px solid var(--color-border)' }}>
                        {renderStatusBadge(mat.extractionStatus)}

                        <div style={{ color: 'var(--color-text-muted)', display: 'flex', alignItems: 'center', gap: '4px', fontSize: '13px' }}>
                          열기 <ExternalLink size={14} />
                        </div>
                      </div>
                    </div>
                ))}
              </div>
          )}
        </div>
        <style>{`
        @keyframes bounce {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-10px); }
        }
      `}</style>
      </div>
  );
}