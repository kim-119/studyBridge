import React from 'react';
import MobileScreen from '../shell/MobileScreen';

export default function PendingScreen({ title, description, showBackButton = false }) {
  return (
    <MobileScreen title={title} showBackButton={showBackButton}>
      <p className="mobile-notice">{description}</p>
    </MobileScreen>
  );
}
