// Página provisional para features de fases futuras.
export default function Placeholder({ title }: { title: string }) {
  return (
    <div className="card grid h-64 place-items-center p-8 text-center">
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        <p className="mt-2 text-sm text-ink-muted dark:text-slate-400">
          Próximamente — esta sección llega en una fase posterior.
        </p>
      </div>
    </div>
  );
}
