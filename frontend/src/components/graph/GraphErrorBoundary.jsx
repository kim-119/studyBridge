import React from 'react';

// 그래프 렌더 실패 시 fallback(주로 LegacyMindMapView)으로 전환하는 경계.
export default class GraphErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error) {
    // eslint-disable-next-line no-console
    console.error('[ObsidianGraph] 렌더 실패 → fallback', error);
  }

  render() {
    if (this.state.hasError) return this.props.fallback || null;
    return this.props.children;
  }
}
