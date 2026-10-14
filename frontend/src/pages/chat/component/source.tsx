
import styles from './source.module.scss'
import LiteratureMetadata from './literature-metadata'
import { safeExternalUrl, type Paper } from '@/api/research-types'

export default function Source(props: {
  list: API.ChatItem['search_results']
}) {
  const { list } = props

  return (
    <div className={styles['source__list']}>
      {list?.map((source) => (
        <div key={source.id} style={{ width: '100%' }}><a
          className={styles['source__item']}
          key={source.id}
          href={safeExternalUrl(source.url)}
          target="_blank"
          rel="noopener noreferrer"
        >
          {source.siteIcon && <img className={styles['icon']} src={source.siteIcon} alt="" />}
          <div className={styles['info']}>
            <span className={styles['host']}>{source.host}</span>
            <span className={styles['name']} title={source.name}>
              {source.name}
            </span>
          </div>
        </a><LiteratureMetadata paper={source as unknown as Partial<Paper>} excerpt /></div>
      ))}
    </div>
  )
}
