export default function App() {
  return (
    <div className="shell">
      <header className="masthead">
        <a className="brand" href="/" aria-label="Simulation Console home">
          <img src="/favicon.svg" alt="" width="32" height="32" />
          <span>Simulation Console</span>
        </a>
        <span className="environment">Local development</span>
      </header>

      <main>
        <p className="eyebrow">ROAD TO START HACK · REVEL8 CHALLENGE</p>
        <h1>A clear view of every exchange.</h1>
        <p className="intro">
          A workspace for autonomous simulations, from the first contact to the
          final replay.
        </p>

        <section className="empty-state" aria-labelledby="workspace-title">
          <div className="empty-symbol" aria-hidden="true">◎</div>
          <h2 id="workspace-title">Your workspace starts here</h2>
          <p>
            The application foundation is ready. Run controls, conversations, and
            evidence will appear here as they are built.
          </p>
          <p className="note">No simulations are running.</p>
        </section>
      </main>

      <footer>Simulation environment · All persona contact stays inside the Target API.</footer>
    </div>
  )
}
