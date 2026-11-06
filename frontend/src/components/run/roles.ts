import {
  BookOpen,
  Brain,
  Calculator,
  FileText,
  type LucideIcon,
  Network,
  Search,
  Sigma,
} from "lucide-react";

const ROLE_ICON: Record<string, LucideIcon> = {
  supervisor: Network,
  literature: BookOpen,
  reasoner: Brain,
  compute: Calculator,
  formalizer: Sigma,
  critic: Search,
  synthesizer: FileText,
};

export function roleIcon(role: string): LucideIcon {
  return ROLE_ICON[role] ?? Brain;
}
