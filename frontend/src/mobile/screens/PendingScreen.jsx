import React from 'react';
import MobileScreen from '../shell/MobileScreen';

export default function PendingScreen({ title, description }) {
  return (
    <MobileScreen title={title}>
      <section className="mobile-notice">
        <span className="mobile-notice__title">{title}</span>
        <p>{description}</p>
      </section>
    </MobileScreen>
  );
}
