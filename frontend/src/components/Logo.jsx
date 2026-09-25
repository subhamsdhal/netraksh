import netrakshLogo from '../assets/netraksh-logo.jpeg';

// The real NETRAKSH brand mark (shield + watchtower + camera-aperture eye),
// supplied by the team as a raster asset. Rendered as a plain <img> so any
// crop or theme changes just mean swapping the file at src/assets — no SVG
// path data to keep in sync with the real artwork.
export default function Logo({ size = 24, withWordmark = false, className = '' }) {
  const mark = (
    <img
      src={netrakshLogo}
      alt="NETRAKSH"
      width={size}
      height={size}
      style={{ width: size, height: size, objectFit: 'cover', borderRadius: '20%' }}
      className={className}
    />
  );

  if (!withWordmark) return mark;

  return (
    <div className="flex items-center gap-2">
      {mark}
      <span className="font-display font-bold tracking-widest text-main" style={{ fontSize: size * 0.4 }}>
        NETRAKSH
      </span>
    </div>
  );
}
