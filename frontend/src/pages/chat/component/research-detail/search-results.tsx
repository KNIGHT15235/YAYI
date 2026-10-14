
import { FileTextOutlined } from '@ant-design/icons'
import styles from './search-results.module.scss'
import type { SearchResult } from './index'
import LiteratureMetadata from '../literature-metadata'
import { safeExternalUrl } from '@/api/research-types'

interface SearchResultsProps {
  data?: SearchResult[]
}

export default function SearchResults({ data }: SearchResultsProps) {
  if (!data?.length) {
    return (
      <div className={styles.empty}>
        <FileTextOutlined className={styles.emptyIcon} />
        <span>暂无搜索结果</span>
      </div>
    )
  }

  return (
    <div className={styles.list}>
      {data.map((item) => (
        <div
          key={item.id}
          className={styles.item}
          onClick={() => { const url = safeExternalUrl(item.url); if (url) window.open(url, '_blank', 'noopener,noreferrer') }}
        >
          <div className={styles.icon}>
            <FileTextOutlined />
          </div>
          <div className={styles.content}>
            <div className={styles.title}>{item.title}</div>
            <div className={styles.meta}>
              <span className={styles.source}>{item.source}</span>
              {item.date && <span className={styles.date}>{item.date}</span>}
            </div>
            {item.snippet && <div className={styles.snippet}>{item.snippet}</div>}
            <LiteratureMetadata paper={item} excerpt />
          </div>
          <div className={styles.arrow}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
        </div>
      ))}
    </div>
  )
}
