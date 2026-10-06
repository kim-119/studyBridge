import React from 'react';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    console.error('화면을 그리는 중 오류가 발생했습니다.', error, info);
  }

  reset = () => {
    this.setState({ hasError: false });
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div className="mobile-boot">
        <span className="mobile-boot__brand">StudyBridge</span>
        <p className="mobile-boot__message">
          <span>화면을 표시하는 중 문제가 발생했습니다.</span>
          <span>다시 시도해주세요.</span>
        </p>
        <button type="button" className="mobile-boot__retry" onClick={this.reset}>
          다시 시도
        </button>
      </div>
    );
  }
}
