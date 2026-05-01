KDIR ?= /lib/modules/$(shell uname -r)/build

obj-m += tcp_bbr_gain110.o
obj-m += tcp_bbr_gain115.o
obj-m += tcp_bbr_gain120.o

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean
