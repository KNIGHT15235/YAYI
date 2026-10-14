
import classNames from 'classnames'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/common'
import markedKatex from 'marked-katex-extension'
import { Marked, Renderer, TokenizerAndRendererExtension } from 'marked'
import { useMemo } from 'react'
import './index.scss'
import 'highlight.js/styles/github.css'
import 'katex/dist/katex.min.css'

export default function Markdown(props: {
  className?: string
  value?: string
  extensions?: TokenizerAndRendererExtension[]
}) {
  const { value, extensions, className, ...otherProps } = props

  const html = useMemo(() => {
    const renderer = new Renderer()
    const escapeAttribute = (text: string) => text.replace(/[&<>"']/g, (char) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[char]!)
    renderer.code = ({ text, lang }) => {
      const language = (lang || '').trim().split(/\s+/)[0]
      const supported = language && hljs.getLanguage(language)
      const content = supported
        ? hljs.highlight(text, { language, ignoreIllegals: true }).value
        : escapeAttribute(text)
      const languageClass = supported ? ` language-${escapeAttribute(language)}` : ''
      return `<pre><code class="hljs${languageClass}">${content}</code></pre>`
    }

    // 自定义图片渲染：只渲染有效的图片 URL，隐藏无效的图片引用
    renderer.image = ({ href, title, text }: { href: string; title: string | null; text: string }) => {
      // 只渲染 base64 data URL 或有效的 http(s) URL
      if (href && (href.startsWith('data:image/') || href.startsWith('http://') || href.startsWith('https://'))) {
        const titleAttr = title ? ` title="${escapeAttribute(title)}"` : ''
        return `<img src="${escapeAttribute(href)}" alt="${escapeAttribute(text || '')}"${titleAttr} class="markdown-image" loading="lazy" />`
      }
      // 无效的图片 URL，直接隐藏（实际图表在"可视化图表"tab中显示）
      return ''
    }

    const marked = new Marked({
      extensions: props.extensions,
    })
    marked.use(markedKatex({ throwOnError: false, trust: false, strict: 'warn', nonStandard: true }))
    const html = marked.parse(props.value ?? '', {
      gfm: true,
      async: false,
      renderer,
    })

    // 过滤原始 HTML、危险 URL 和自定义扩展输出，保留报告表格和图片。
    return DOMPurify.sanitize(html, { USE_PROFILES: { html: true, svg: true, mathMl: true } })
  }, [value, extensions])

  return (
    <div
      className={classNames('com-markdown', className)}
      {...otherProps}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
