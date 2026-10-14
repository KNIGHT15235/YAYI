
import * as api from '@/api'
import { authActions } from '@/store/auth'
import { ArrowRightOutlined, LockOutlined, MailOutlined, UserOutlined } from '@ant-design/icons'
import { Button, Form, Input, message } from 'antd'
import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import styles from './login.module.scss'
import Brand from '@/components/brand'

function ResearchOrbit() {
  return (
    <div className={styles['research-orbit']} aria-hidden="true">
      <svg viewBox="0 0 520 310" fill="none">
        <defs>
          <radialGradient id="research-glow"><stop stopColor="#247CFA" stopOpacity=".32" /><stop offset="1" stopColor="#247CFA" stopOpacity="0" /></radialGradient>
          <linearGradient id="research-ring" x1="80" y1="70" x2="430" y2="240" gradientUnits="userSpaceOnUse"><stop stopColor="#73DBFF" stopOpacity=".65" /><stop offset=".5" stopColor="#357BF0" stopOpacity=".12" /><stop offset="1" stopColor="#8BCFFF" stopOpacity=".65" /></linearGradient>
        </defs>
        <ellipse cx="260" cy="155" rx="220" ry="152" fill="url(#research-glow)" />
        <g stroke="url(#research-ring)">
          <ellipse cx="260" cy="155" rx="206" ry="76" transform="rotate(-20 260 155)" />
          <ellipse cx="260" cy="155" rx="181" ry="104" transform="rotate(31 260 155)" />
          <circle cx="260" cy="155" r="113" strokeDasharray="2 9" />
          <circle cx="260" cy="155" r="66" />
          <path d="M85 119L260 155L420 93M133 246L260 155L407 239M188 52L260 155L333 275" strokeOpacity=".4" />
          <path d="M85 119L188 52L420 93L407 239L133 246Z" strokeOpacity=".22" />
        </g>
        <g fill="#87D5FF">
          <circle cx="85" cy="119" r="4" /><circle cx="188" cy="52" r="3" /><circle cx="420" cy="93" r="4" /><circle cx="133" cy="246" r="4" /><circle cx="407" cy="239" r="3" />
          <circle cx="333" cy="275" r="2" /><circle cx="358" cy="61" r="2" /><circle cx="59" cy="177" r="2" /><circle cx="456" cy="179" r="2" />
        </g>
        <circle cx="85" cy="119" r="10" stroke="#75CBFF" strokeOpacity=".2" />
        <circle cx="420" cy="93" r="10" stroke="#75CBFF" strokeOpacity=".2" />
        <circle cx="260" cy="155" r="53" fill="#08172A" stroke="#5BA5FF" strokeOpacity=".4" />
        <image href="/yayi-logo.png" x="216" y="111" width="88" height="88" />
        <g fill="#BDCEE6" fontSize="12" fontFamily="inherit" letterSpacing="2">
          <text x="45" y="101">文献</text><text x="430" y="77">假设</text><text x="92" y="276">证据</text><text x="422" y="263">洞见</text>
        </g>
      </svg>
    </div>
  )
}

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [loading, setLoading] = useState(false)
  const [isLogin, setIsLogin] = useState(true)

  const from = (location.state as any)?.from?.pathname || '/'

  const onLogin = async (values: { username: string; password: string }) => {
    setLoading(true)
    try {
      const { data } = await api.auth.login(values)
      authActions.login(data.access_token, data.user)
      message.success('登录成功')
      navigate(from, { replace: true })
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  const onRegister = async (values: {
    username: string
    email: string
    password: string
    confirmPassword: string
  }) => {
    if (values.password !== values.confirmPassword) {
      message.error('两次输入的密码不一致')
      return
    }

    setLoading(true)
    try {
      const { data } = await api.auth.register({
        username: values.username,
        email: values.email,
        password: values.password,
      })
      authActions.login(data.access_token, data.user)
      message.success('注册成功')
      navigate(from, { replace: true })
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '注册失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className={styles['login-page']}>
      <div className={styles['login-container']}>
        {/* 左侧品牌区域 */}
        <div className={styles['brand-section']}>
          <div className={styles['brand-header']}>
            <Brand />
            <span className={styles['brand-edition']}>AI–SCIENTIST</span>
          </div>
          <div className={styles['brand-content']}>
            <p className={styles['brand-eyebrow']}>RESEARCH WITH EVIDENCE</p>
            <h1 className={styles['brand-title']}>让每一次探索，<br /><span>都有据可循。</span></h1>
            <p className={styles['brand-subtitle']}>从一个研究问题出发，连接文献、验证假设，<br />让新的洞见自然浮现。</p>
          </div>
          <ResearchOrbit />
          <div className={styles['brand-features']}>
            <span>文献检索</span><i /><span>证据核验</span><i /><span>知识沉淀</span>
          </div>
        </div>

        {/* 右侧表单区域 */}
        <div className={styles['form-section']}>
          <div className={styles['form-container']}>
            <div className={styles['form-header']}>
              <div className={styles['form-eyebrow']}><span /> 雅意科研工作台</div>
              <h2>{isLogin ? '欢迎回来' : '开启新的探索'}</h2>
              <p>{isLogin ? '登录雅意，继续你的下一次发现。' : '创建账户，让研究从这里开始。'}</p>
            </div>

            {isLogin ? (
              <Form
                key="login"
                name="login"
                onFinish={onLogin}
                autoComplete="off"
                layout="vertical"
                requiredMark={false}
              >
                <Form.Item
                  name="username"
                  label="用户名"
                  rules={[{ required: true, message: '请输入用户名' }]}
                >
                  <Input
                    prefix={<UserOutlined className={styles['input-icon']} />}
                    placeholder="请输入用户名"
                    autoComplete="username"
                    size="large"
                    className={styles['form-input']}
                  />
                </Form.Item>

                <Form.Item
                  name="password"
                  label="密码"
                  rules={[{ required: true, message: '请输入密码' }]}
                >
                  <Input.Password
                    prefix={<LockOutlined className={styles['input-icon']} />}
                    placeholder="密码"
                    autoComplete="current-password"
                    size="large"
                    className={styles['form-input']}
                  />
                </Form.Item>

                <Form.Item>
                  <Button
                    type="primary"
                    htmlType="submit"
                    loading={loading}
                    block
                    size="large"
                    className={styles['submit-btn']}
                  >
                    <span>登录工作台</span><ArrowRightOutlined />
                  </Button>
                </Form.Item>
              </Form>
            ) : (
              <Form
                key="register"
                name="register"
                onFinish={onRegister}
                autoComplete="off"
                layout="vertical"
                requiredMark={false}
              >
                <Form.Item
                  name="username"
                  label="用户名"
                  rules={[
                    { required: true, message: '请输入用户名' },
                    { min: 3, message: '用户名至少3个字符' },
                  ]}
                >
                  <Input
                    prefix={<UserOutlined className={styles['input-icon']} />}
                    placeholder="用户名"
                    autoComplete="username"
                    size="large"
                    className={styles['form-input']}
                  />
                </Form.Item>

                <Form.Item
                  name="email"
                  label="邮箱"
                  rules={[
                    { required: true, message: '请输入邮箱' },
                    { type: 'email', message: '请输入有效的邮箱地址' },
                  ]}
                >
                  <Input
                    prefix={<MailOutlined className={styles['input-icon']} />}
                    placeholder="邮箱"
                    autoComplete="email"
                    size="large"
                    className={styles['form-input']}
                  />
                </Form.Item>

                <Form.Item
                  name="password"
                  label="密码"
                  rules={[
                    { required: true, message: '请输入密码' },
                    { min: 6, message: '密码至少6个字符' },
                  ]}
                >
                  <Input.Password
                    prefix={<LockOutlined className={styles['input-icon']} />}
                    placeholder="密码"
                    autoComplete="new-password"
                    size="large"
                    className={styles['form-input']}
                  />
                </Form.Item>

                <Form.Item
                  name="confirmPassword"
                  label="确认密码"
                  rules={[{ required: true, message: '请确认密码' }]}
                >
                  <Input.Password
                    prefix={<LockOutlined className={styles['input-icon']} />}
                    placeholder="确认密码"
                    autoComplete="new-password"
                    size="large"
                    className={styles['form-input']}
                  />
                </Form.Item>

                <Form.Item>
                  <Button
                    type="primary"
                    htmlType="submit"
                    loading={loading}
                    block
                    size="large"
                    className={styles['submit-btn']}
                  >
                    <span>创建账户</span><ArrowRightOutlined />
                  </Button>
                </Form.Item>
              </Form>
            )}

            <div className={styles['form-footer']}>
              <span className={styles['switch-text']}>
                {isLogin ? '还没有账户？' : '已有账户？'}
              </span>
              <button
                type="button"
                className={styles['switch-btn']}
                onClick={() => setIsLogin(!isLogin)}
              >
                {isLogin ? '立即注册' : '返回登录'}
              </button>
            </div>
          </div>
        </div>
      </div>
      <footer className={styles['page-footer']}>YAYI 雅意<span>·</span>让研究回归发现</footer>
    </main>
  )
}
