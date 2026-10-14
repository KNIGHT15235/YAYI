
import './spinner.scss'

export default function ComSpinner() {
  return (
    <div className="com-spinner" role="status" aria-label="雅意正在加载">
      <div className="com-spinner__bounce1"></div>
      <div className="com-spinner__bounce2"></div>
      <div className="com-spinner__bounce3"></div>
    </div>
  )
}
