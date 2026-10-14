
import ComSpinner from '@/components/spin/spinner'
import { ChatRole } from '@/configs'
import classNames from 'classnames'
import styles from './chat-message.module.scss'
import { Result } from './result'
import { researchMessageVersions } from '@/utils/research-message-versions'

function UserMessage(props: { item: API.ChatItem }) {
  const { item } = props

  return (
    <div className={classNames(styles['chat-message-item--user'])}>
      {item.content}
    </div>
  )
}

function AssistantMessage(props: {
  item: API.ChatItem
  isEnd?: boolean
  onSend?: (text: string) => void
  onOpenCiations?: () => void
  onStepClick?: (stepId: string) => void
}) {
  const { item, isEnd, onSend, onStepClick } = props

  return (
    <div
      className={classNames(
        styles['chat-message-item'],
        styles['chat-message-item--assistant'],
      )}
    >
      <Result item={item} isEnd={isEnd} onSend={onSend} onStepClick={onStepClick} />

      {item.loading ? <ComSpinner /> : null}
    </div>
  )
}

export default function ChatMessage(props: {
  list: API.ChatItem[]
  researchSession?: boolean
  onSend?: (text: string) => void
  onOpenCiations?: (item: API.ChatItem) => void
  onStepClick?: (stepId: string) => void
}) {
  const { list, researchSession = false, onSend, onOpenCiations, onStepClick } = props
  const versions = researchMessageVersions(list, researchSession)

  return (
    <div className={styles['chat-message']}>
      {list.map((item, index) => {
        if (item.role === ChatRole.User) {
          return <UserMessage key={item.id} item={item} />
        }

        const assistant = (
          <AssistantMessage
            key={item.id}
            item={item}
            isEnd={list.length - 1 === index}
            onSend={onSend}
            onOpenCiations={() => onOpenCiations?.(item)}
            onStepClick={onStepClick}
          />
        )
        const version = versions.get(item.id)
        if (!version) return assistant
        if (!version.latest) return <details key={item.id} className={styles['report-revision']}>
          <summary>
            <span>修订前版本（展开查看） · 第 {version.number} / {version.total} 版</span>
            <span className={styles['report-revision-title']} title={version.title}>{version.title}</span>
          </summary>
          {assistant}
        </details>
        return <div key={item.id}>
          <div className={styles['report-current-version']}>当前版本 · 第 {version.number} / {version.total} 版</div>
          {assistant}
        </div>
      })}
    </div>
  )
}
