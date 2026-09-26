`timescale 1ns/1ps
module router_backpressure;
reg clk=0; always #5 clk=~clk;
reg resetn=0;
reg [7:0] rx_byte=0;
reg rx_byte_valid=0,rx_first=0,cs_active=0;
wire [7:0] msg_type,msg_seq,payload_data;
wire [15:0] msg_len;
wire msg_start,payload_valid,payload_ready,frame_done,enc_abort;
wire [7:0] enc_data; wire enc_valid;
reg enc_ready=0;
reg boot_ready_in=0,mbox_pending=0;
wire mbox_out_done;
wire [5:0] mbox_out_idx;
cm0_router_ctrl router(
 .clk(clk),.resetn(resetn),.rx_byte(rx_byte),.rx_byte_valid(rx_byte_valid),
 .rx_first(rx_first),.cs_active(cs_active),.wr_ready(1'b1),
 .rd_byte(8'h0),.rd_valid(1'b0),.rd_done(1'b0),
 .msg_type(msg_type),.msg_seq(msg_seq),.msg_len(msg_len),.msg_start(msg_start),
 .payload_data(payload_data),.payload_valid(payload_valid),.payload_ready(payload_ready),
 .frame_done(frame_done),.enc_abort(enc_abort),
 .mbox_pending(mbox_pending),.mbox_out_len(6'd2),.mbox_out_idx(mbox_out_idx),
 .mbox_out_data(mbox_out_idx==0 ? 8'h42 : 8'h43),.mbox_out_done(mbox_out_done),
 .abort_in(1'b0),.status_flags(8'hc0),.boot_ready_in(boot_ready_in),
 .swap_ready_in(1'b0),.quiesce_active(1'b0)
);
cm0_frame_enc encoder(
 .clk(clk),.resetn(resetn),.msg_type(msg_type),.msg_seq(msg_seq),.msg_len(msg_len),
 .msg_start(msg_start),.abort(enc_abort),.payload_data(payload_data),
 .payload_valid(payload_valid),.payload_ready(payload_ready),
 .enc_data(enc_data),.enc_valid(enc_valid),.enc_ready(enc_ready),.frame_done(frame_done)
);
integer starts=0, completions=0, tick=0;
reg busy=0;
always @(posedge clk) if(resetn) begin
 tick<=tick+1;
 if(msg_start) begin
  if(busy && !frame_done) $fatal(1,"router starts a frame before encoder completion");
  starts<=starts+1; busy<=1;
 end
 if(frame_done) begin completions<=completions+1; busy<=0; end
 if(enc_valid && enc_ready) $display("BYTE %02x",enc_data);
 if(mbox_out_done && !frame_done && busy) $fatal(1,"mailbox released before transmission completes");
end
initial begin
 repeat(5) @(negedge clk); resetn=1;
 boot_ready_in=1; @(negedge clk); boot_ready_in=0;
 // Leave a mailbox queued while the boot notification's UART is blocked.
 mbox_pending=1;
 repeat(30) @(negedge clk); enc_ready=1;
 wait(mbox_out_done); @(negedge clk); mbox_pending=0;
 wait(completions==2);
 repeat(5) @(negedge clk);
 cs_active=1;rx_byte=8'h05;rx_byte_valid=1;rx_first=1;
 @(negedge clk);rx_byte=8'h27;rx_first=0;
 @(negedge clk);rx_byte_valid=0;cs_active=0;
 // Repeated stalls model UART CTS backpressure without losing bytes.
 repeat(20) begin enc_ready=0;repeat(3) @(negedge clk);enc_ready=1;repeat(2) @(negedge clk);end
 wait(completions==3);
 repeat(3) @(negedge clk);
 if(starts!=3) $fatal(1,"unexpected frame count %d",starts);
 $display("PASS backpressure notification mailbox status");$finish;
end
initial begin #100000; $fatal(1,"router stalled"); end
endmodule
