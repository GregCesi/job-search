// Libellé et couleur d'une catégorie (sortis de pages/offers/[id].vue, EXE-205).
const CATEGORY_LABELS: Record<string, string> = {
  parfait: '★ Parfait',
  reve: '◈ Rêve',
  atteignable: '✓ Atteignable',
  hors: '✗ Hors',
  hors_perimetre: '⊘ Hors-périmètre',
}

export function categoryLabel(cat: string | null | undefined): string {
  return cat ? (CATEGORY_LABELS[cat] ?? cat) : '?'
}

export function categoryBadgeClass(cat: string | null | undefined): string {
  if (cat === 'parfait')        return 'bg-green-50 border-green-300 text-green-700'
  if (cat === 'reve')           return 'bg-indigo-50 border-indigo-300 text-indigo-700'
  if (cat === 'atteignable')    return 'bg-amber-50 border-amber-300 text-amber-700'
  if (cat === 'hors')           return 'bg-gray-100 border-gray-400 text-gray-600'
  if (cat === 'hors_perimetre') return 'bg-slate-100 border-slate-400 text-slate-600'
  return 'bg-gray-100 border-gray-200 text-gray-500'
}
