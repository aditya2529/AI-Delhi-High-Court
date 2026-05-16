import { SearchFlow } from "@/components/forms/SearchFlow";

export default function HomePage() {
  return (
    <section className="dhc-search-page">
      <h2>Track a Delhi High Court case</h2>
      <p className="dhc-lede">
        Enter your case type, number, and year. Solve the CAPTCHA from the
        court. We'll fetch the latest status, simplified.
      </p>
      <SearchFlow />
    </section>
  );
}
