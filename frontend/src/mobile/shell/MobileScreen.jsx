import React from 'react';
import MobileAppBar from './MobileAppBar';

export default function MobileScreen({ title, showBackButton = false, actions = null, children }) {
  return (
    <>
      <MobileAppBar title={title} showBackButton={showBackButton} actions={actions} />
      <main className="mobile-screen">{children}</main>
    </>
  );
}
