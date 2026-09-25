import React from 'react';

/**
 * 푸터 (레퍼런스 톤).
 *  - 상단 보더만(별도 배경 없이 페이지 배경), 좌 로고+소개 / 우 COMPANY / 하단 저작권.
 */
const COMPANY_LINKS = ['이용약관', '개인정보처리방침', '고객센터'];

export default function Footer() {
  return (
    <footer className="border-t border-gray-200">
      <div className="mx-auto max-w-6xl px-6 py-12">
        <div className="grid gap-8 md:grid-cols-2">
          <div>
            <span className="text-lg font-extrabold text-green-600">StudyBridge</span>
            <p className="mt-3 max-w-xs text-sm leading-relaxed text-gray-500">
              AI 기술로 대학생들의 학습 경험을 혁신하는 에듀테크 플랫폼입니다.
            </p>
          </div>
          <div className="md:text-right">
            <h4 className="text-sm font-semibold text-gray-900">COMPANY</h4>
            <ul className="mt-3 space-y-2 text-sm text-gray-500">
              {COMPANY_LINKS.map((label) => (
                <li key={label}><a href="#" className="hover:text-gray-900">{label}</a></li>
              ))}
            </ul>
          </div>
        </div>
        <div className="mt-8 border-t border-gray-200 pt-8 text-xs text-gray-400">
          © 2024 StudyBridge. All rights reserved.
        </div>
      </div>
    </footer>
  );
}
