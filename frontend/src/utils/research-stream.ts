/** Each subscription owns its abort signal and generation; old streams cannot update a new view. */
export interface StreamTicket {
  sessionId: string
  generation: number
  controller: AbortController
}

export class ResearchStreamScope {
  private generation = 0
  private current?: StreamTicket

  get revision() { return this.generation }

  begin(sessionId: string): StreamTicket {
    this.close()
    this.current = { sessionId, generation: this.generation, controller: new AbortController() }
    return this.current
  }

  accepts(ticket: StreamTicket, eventRunId?: unknown): boolean {
    return this.current === ticket && ticket.generation === this.generation
      && !ticket.controller.signal.aborted
      && (eventRunId == null || eventRunId === ticket.sessionId)
  }

  close() {
    this.current?.controller.abort()
    this.current = undefined
    this.generation += 1
  }
}
