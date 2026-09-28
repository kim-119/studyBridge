import React from 'react';
import MobileAppBar from './MobileAppBar';

export default function MobileScreen({ title = null, showBackButton = false, actions = null, children }) {
  return (
    <>
      <MobileAppBar title={title} showBackButton={showBackButton} actions={actions} />

      <main className="mobile-screen">
        {!showBackButton && title && <h1 className="mobile-screen__title">{title}</h1>}
        {children}
      </main>
    </>
  );
}
