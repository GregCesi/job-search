// Date et heure ISO rendues par l'API, affichées JJ/MM/AAAA au jour de
// Bruxelles (EXE-224) ; rien si la date manque ou ne se lit pas.
const FORMAT = new Intl.DateTimeFormat('fr-BE', {
  timeZone: 'Europe/Brussels',
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
})

export function jourDeBruxelles(iso: string | null | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '' : FORMAT.format(date)
}
