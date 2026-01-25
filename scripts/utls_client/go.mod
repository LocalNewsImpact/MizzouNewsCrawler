module local/utls-client

go 1.24.0

toolchain go1.24.11

// require github.com/refraction-networking/utls left to be resolved via `go get`

require (
	github.com/refraction-networking/utls v1.8.1
	golang.org/x/crypto v0.46.0
)

require (
	github.com/andybalholm/brotli v1.0.6 // indirect
	github.com/cloudflare/circl v1.3.7 // indirect
	github.com/klauspost/compress v1.17.4 // indirect
	github.com/quic-go/quic-go v0.40.1 // indirect
	golang.org/x/net v0.48.0 // indirect
	golang.org/x/sys v0.39.0 // indirect
	golang.org/x/text v0.32.0 // indirect
)

replace github.com/refraction-networking/utls => ../../third_party/utls
