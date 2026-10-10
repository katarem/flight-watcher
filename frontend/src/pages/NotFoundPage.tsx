import { Compass } from 'lucide-react'
import { Link } from 'react-router'
import { buttonClass } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/feedback'
import { useTitle } from '@/lib/hooks'

export function NotFoundPage() {
  useTitle('No encontrado')
  return (
    <EmptyState icon={<Compass />} title="Esta página no existe" action={<Link to="/" className={buttonClass()}>Volver al panel</Link>}>
      Puede que el enlace sea antiguo o que la vigilancia se haya eliminado.
    </EmptyState>
  )
}
