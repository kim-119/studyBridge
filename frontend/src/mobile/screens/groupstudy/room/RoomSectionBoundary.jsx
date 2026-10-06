import React from 'react';

export default class RoomSectionBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    console.error(`스터디룸 ${this.props.sectionName} 영역을 그리는 중 오류가 발생했습니다.`, error, info);
  }

  reset = () => {
    this.setState({ hasError: false });
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <p className="mobile-room-notice is-error" role="alert" data-room-section-error={this.props.sectionName}>
        <span>{this.props.sectionName}을(를) 표시하지 못했습니다. 다른 기능은 계속 사용할 수 있습니다.</span>
        <button type="button" className="mobile-room-notice__action" onClick={this.reset}>
          다시 시도
        </button>
      </p>
    );
  }
}
