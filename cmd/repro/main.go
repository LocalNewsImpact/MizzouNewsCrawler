package main

import (
	"fmt"
	"os"
	tlsmod "github.com/refraction-networking/utls"
)

func main() {
	fmt.Println("Starting ReproFromTestdata()")
	if err := tlsmod.ReproFromTestdata(); err != nil {
		fmt.Fprintln(os.Stderr, "Reproducer failed:", err)
		os.Exit(1)
	}
	fmt.Println("Reproducer succeeded")
}

