
import { AxiosResponse } from 'axios'

export class ResponseError extends Error {
  response: AxiosResponse<any> | undefined

  constructor(message: string, response?: AxiosResponse<any>) {
    super(message)
    this.response = response
  }
}

export async function getRequestErrorMessage(error: unknown, fallback: string): Promise<string> {
  const cause = error as { message?: string; response?: { data?: unknown } }
  let data = cause?.response?.data
  if (data instanceof ReadableStream) {
    data = await new Response(data).json().catch(() => null)
  }
  const detail = (data as { detail?: unknown } | null)?.detail
  if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') return detail.message
  return typeof detail === 'string' ? detail : cause?.message || fallback
}
