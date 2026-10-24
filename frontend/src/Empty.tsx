export function Empty({ title, children }: { title: string; children: string }) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-sheet px-4 py-10 text-center">
      <p className="font-bold">{title}</p>
      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-muted">{children}</p>
    </div>
  );
}
