import { notFound } from "next/navigation";
import EvalDashboard from "./EvalDashboard";

export default function EvalsPage() {
  if (process.env.NEXT_PUBLIC_EVALS !== "1") notFound();
  return <EvalDashboard />;
}
