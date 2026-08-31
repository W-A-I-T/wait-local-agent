import { Link, useLocation } from "react-router-dom";

export default function NotFound() {
  const location = useLocation();
  const attemptedPath = `${location.pathname}${location.search}${location.hash}` || "/";

  return (
    <section className="panel" aria-labelledby="not-found-heading">
      <h2 id="not-found-heading">Page not found</h2>
      <p className="screen-note">
        No WAIT page matches <code>{attemptedPath}</code>.
      </p>
      <Link to="/">Return to Overview</Link>
    </section>
  );
}
