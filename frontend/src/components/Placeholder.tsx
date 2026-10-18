// Página provisional para features de fases futuras.
export default function Placeholder({ title }: { title: string }) {
  return (
    <div className="card grid h-64 place-items-center p-8 text-center">
      <div>
        <h1 className="page-title">{title}</h1>
        <p className="mt-2 text-sm text-ink-muted">
          Próximamente — esta sección llega en una fase posterior.
        </p>
      </div>
    </div>
  );
}
