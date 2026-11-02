export function ComingSoon({ title, children }: { title: string; children: string }) {
  return (
    <div className="flex h-full items-center justify-center px-6">
      <div className="max-w-md text-center">
        <h1 className="text-xl font-semibold text-[#0f2744]">{title}</h1>
        <p className="mt-2 text-sm leading-6 text-slate-500">{children}</p>
      </div>
    </div>
  );
}
