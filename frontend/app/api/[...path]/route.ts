import { NextRequest } from "next/server"

const BACKEND_URL = process.env.BACKEND_URL!

async function handler(req: NextRequest, method: string) {
  const path = req.nextUrl.pathname.replace("/api", "")

  const url = `${BACKEND_URL}${path}${req.nextUrl.search}`

  const headers: any = {
    "Content-Type": "application/json",
  }

  // Forward auth + tenant
  const auth = req.headers.get("authorization")
  if (auth) headers["Authorization"] = auth

  const tenant = req.headers.get("x-tenant-id")
  if (tenant) headers["X-Tenant-ID"] = tenant

  const body =
    method !== "GET" && method !== "HEAD"
      ? await req.text()
      : undefined

  const res = await fetch(url, {
    method,
    headers,
    body,
  })

  const text = await res.text()

  return new Response(text, {
    status: res.status,
    headers: {
      "Content-Type": "application/json",
    },
  })
}

export async function GET(req: NextRequest) {
  return handler(req, "GET")
}

export async function POST(req: NextRequest) {
  return handler(req, "POST")
}

export async function PUT(req: NextRequest) {
  return handler(req, "PUT")
}

export async function DELETE(req: NextRequest) {
  return handler(req, "DELETE")
}
