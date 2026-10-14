
import IconBid from '@/assets/layout/bid.svg'
import IconHistory from '@/assets/layout/history.svg'
import IconHome from '@/assets/layout/home.svg'
import IconKnowledge from '@/assets/layout/knowledge.svg'
import IconMemory from '@/assets/layout/memory.svg'
import IconDatabase from '@/assets/layout/database.svg'
import IconNewChat from '@/assets/layout/newchat.svg'
import IconNews from '@/assets/layout/news.svg'
import React, { useMemo } from 'react'
import { useLocation } from 'react-router-dom'
import { useSnapshot } from 'valtio'
import { Dropdown } from 'antd'
import { DownOutlined } from '@ant-design/icons'
import { NavItem } from './nav-item'
import { industryState, setCurrentIndustry } from '@/store/industry'
import './nav.scss'
import { SCIENCE_MODE } from '@/configs/research'

export function Nav() {
  const { pathname } = useLocation()
  const { currentIndustryId, industries } = useSnapshot(industryState)

  const currentIndustry = useMemo(() => {
    const industry = industries.find((i) => i.id === currentIndustryId)
    console.log('[Nav] 当前行业:', industry?.name)
    return industry || industries[0]
  }, [currentIndustryId, industries])

  const industryMenuItems = useMemo(() => {
    return industries.map((industry) => ({
      key: industry.id,
      label: (
        <div className="industry-menu-item">
          <div className="industry-menu-item__name">{industry.name}</div>
          <div className="industry-menu-item__desc">{industry.description}</div>
        </div>
      ),
      onClick: () => {
        console.log('[Nav] 切换行业:', industry.id, industry.name)
        setCurrentIndustry(industry.id)
      },
    }))
  }, [industries])

  const items = useMemo(
    () => [
      {
        key: 'home',
        label: '首页',
        icon: IconHome,
        href: '/',
      },
      {
        key: 'newchat',
        label: SCIENCE_MODE ? '深度研究' : '新的聊天',
        icon: IconNewChat,
        href: '/chat',
      },
      {
        key: 'history',
        label: SCIENCE_MODE ? '研究历史' : '对话历史',
        icon: IconHistory,
        href: '/history',
      },
      {
        key: 'memory',
        label: '记忆库',
        icon: IconMemory,
        href: '/memory',
      },
      {
        key: 'knowledge',
        label: '知识库管理',
        icon: IconKnowledge,
        href: '/knowledge',
      },
      {
        key: 'database',
        label: '数据库探索',
        icon: IconDatabase,
        href: '/database',
      },
      {
        key: 'news',
        label: SCIENCE_MODE ? '科研资讯' : '行业资讯',
        icon: IconNews,
        href: '/news',
      },
      {
        key: 'bid',
        label: '招投标信息',
        icon: IconBid,
        href: '/bidding',
      },
      // 暂时隐藏职业规划
      // {
      //   key: 'career',
      //   label: '职业规划',
      //   icon: IconCareer,
      //   href: '#',
      // },
    ].filter(item => !SCIENCE_MODE || item.key !== 'bid'),
    [],
  )

  return (
    <>
      {/* 行业选择器 */}
      {!SCIENCE_MODE && <div className="industry-selector">
        <Dropdown
          menu={{
            items: industryMenuItems,
            style: { backgroundColor: '#fff' },
          }}
          trigger={['click']}
          placement="bottomLeft"
          dropdownRender={(menu) => (
            <div
              style={{
                backgroundColor: '#fff',
                borderRadius: 8,
                boxShadow: '0 6px 16px 0 rgba(0, 0, 0, 0.08), 0 3px 6px -4px rgba(0, 0, 0, 0.12)',
                padding: 4,
              }}
            >
              {React.cloneElement(menu as React.ReactElement<{ style?: React.CSSProperties }>, {
                style: {
                  backgroundColor: '#fff',
                  boxShadow: 'none',
                },
              })}
            </div>
          )}
        >
          <div className="industry-selector__trigger">
            <span className="industry-selector__label">{currentIndustry.name}</span>
            <DownOutlined className="industry-selector__icon" />
          </div>
        </Dropdown>
      </div>}

      <nav className="base-layout-nav" aria-label="主导航">
        <span className="base-layout-nav__heading">研究工作台</span>
        {items.map(({ key, ...item }, index) => (
          <React.Fragment key={key}>
            {index === 3 && <span className="base-layout-nav__heading base-layout-nav__heading--resources">研究资源</span>}
            <NavItem
              {...item}
              active={pathname === item.href || (item.href !== '/' && pathname.startsWith(`${item.href}/`))}
            />
          </React.Fragment>
        ))}
      </nav>
    </>
  )
}
