import { Sparkles } from "lucide-react";

export function ComingSoon({ title }: { title: string }) {
  return (
    <section className="panel coming-soon">
      <Sparkles size={24} aria-hidden="true" />
      <h2>{title}</h2>
      <p>This screen is reserved in the application shell for the next workflow increment.</p>
    </section>
  );
}
