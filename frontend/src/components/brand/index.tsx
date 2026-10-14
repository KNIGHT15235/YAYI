export default function Brand({ compact = false }: { compact?: boolean }) {
  const logoSize = compact ? 42 : 56

  return (
    <div
      aria-label="YAYI 雅意"
      style={{
        display: 'flex',
        flexDirection: compact ? 'column' : 'row',
        alignItems: 'center',
        justifyContent: 'center',
        minWidth: 0,
        maxWidth: '100%',
        boxSizing: 'border-box',
        gap: compact ? 3 : 12,
        color: 'inherit',
      }}
    >
      <img
        src="/yayi-logo.png"
        alt="YAYI"
        width={logoSize}
        height={logoSize}
        draggable={false}
        style={{ display: 'block', flexShrink: 0, objectFit: 'contain', borderRadius: '50%' }}
      />
      <span style={{
        display: 'flex',
        flexDirection: compact ? 'column' : 'row',
        alignItems: 'center',
        gap: compact ? 0 : 9,
        whiteSpace: 'nowrap',
        textAlign: 'center',
        lineHeight: compact ? '20px' : '32px',
        fontWeight: 700,
        letterSpacing: compact ? 0.3 : 0.8,
        fontSize: compact ? 16 : 28,
      }}>
        <span>YAYI</span>
        <span style={{ fontWeight: 500, lineHeight: compact ? '16px' : '32px', fontSize: compact ? 12 : 24 }}>雅意</span>
      </span>
    </div>
  )
}
