
import { Footer } from './footer'
import './index.scss'
import { Nav } from './nav'
import Brand from '@/components/brand'
import { Link, useLocation } from 'react-router-dom'
import { useEffect } from 'react'

export function BaseLayout({ children }: { children?: React.ReactNode }) {
  const { pathname } = useLocation()
  useEffect(() => { window.scrollTo(0, 0) }, [pathname])
  return (
    <div className="base-layout">
      <div className="base-layout__sidebar">
        <div className="base-layout__sidebar-main scrollbar-style">
          <Link className="base-layout__brand" to="/" aria-label="YAYI 雅意首页"><Brand compact /></Link>
          <Nav />

          <Footer />
        </div>
      </div>

      <main className="base-layout__content">{children}</main>
    </div>
  )
}
