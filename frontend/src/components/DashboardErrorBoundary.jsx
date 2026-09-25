import { Component } from 'react';

export default class DashboardErrorBoundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error, info) {
    console.error('[Dashboard] Component failure', error, info);
  }

  render() {
    if (this.state.failed) {
      return (
        <section className="card" role="alert" style={{ margin: '1rem', padding: '2rem' }}>
          <h1 className="section-title">Dashboard component failed</h1>
          <p className="text-muted" style={{ marginTop: '0.75rem' }}>
            Live monitoring could not be rendered. Refresh the page or contact the system operator.
          </p>
        </section>
      );
    }
    return this.props.children;
  }
}
