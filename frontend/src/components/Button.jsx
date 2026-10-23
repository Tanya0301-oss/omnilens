import { Link } from 'react-router-dom';

/**
 * Button — shared primary action component used on both the landing
 * page and the real dashboard. Renders as <Link>, <a>, or <button>
 * depending on whether `to` or `href` is supplied.
 */
export default function Button({ children, to, href, onClick, disabled, className = '' }) {
  const cls = `btn-primary ${className}`.trim();

  if (to) {
    return (
      <Link to={to} className={cls}>
        {children}
      </Link>
    );
  }

  if (href) {
    return (
      <a href={href} className={cls}>
        {children}
      </a>
    );
  }

  return (
    <button className={cls} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  );
}
