            // based on goblin's p2pool-stats project
			var period = "day";
            var siteTitle = "Drazisil's P2Pool";

			function LoadData()
			{
				$("#blocks").html("<tr><th>ID</th><th>Time</th><th>Hash / Explorer link</th><th>Share</th></tr>");
				$("#payouts").html("<tr><th>address</th><th>amount in <span class=\"symbol\"></span></th></tr>");
                $("#miners").html("<tr><th>Miner</th><th>Hashrate</th><th>Dead hashrate</th></tr>");
				function values(o){ res = []; for(var x in o) res.push(o[x]); return res; }
				
				d3.json('/web/version', function(version) {
					d3.selectAll('#version').text(version);
			    });
			    
			    d3.json('/web/currency_info', function(currency_info) {
				d3.selectAll('.symbol').text(currency_info.symbol);
				
				d3.json('/current_payouts', function(pays) {
				    d3.json('/payout_addr', function(addr) {
				        d3.select('#payout_addr').text(addr);
				        d3.select('#payout_amount').text(addr in pays ? pays[addr] : 0);
				    });
				    
				    var arr = []; for(var i in pays) arr.push(i); arr.sort(function(a, b){return pays[b] - pays[a]});
				    
				    var tr = d3.select('#payouts').selectAll().data(arr).enter().append('tr');
				    tr.append('td').append('a').text(function(addr){return addr}).attr('href', function(addr){return currency_info.address_explorer_url_prefix + addr});
				    tr.append('td').text(function(addr){return pays[addr]});
				    
				    var total_tr = d3.select('#payouts').append('tr');
				    total_tr.append('td').append('strong').text('Total');
				    total_tr.append('td').text(d3.sum(arr, function(addr){return pays[addr]}).toFixed(8));
				});
				
				d3.json('/recent_blocks', function(blocks) {
				    var tr = d3.select('#blocks').selectAll().data(blocks).enter().append('tr');
				    tr.append('td').text(function(block){return block.number});
				    tr.append('td').text(function(block){return new Date(1000*block.ts).toString()});
				    tr.append('td').append('a').text(function(block){return block.hash}).attr('href', function(block){return currency_info.block_explorer_url_prefix + block.hash});
				    tr.append('td').append('a').text('->').attr('href', function(block){return 'share.html#' + block.share});
				});
			    });
			    
				$("#best_share").html("");
				$("#verified_heads").html("");
				$("#heads").html("");
				$("#verified_tails").html("");
				$("#tails").html("");
			    d3.json('/web/best_share_hash', function(c) {
				d3.select('#best_share').append('a').attr('href', 'share.html#' + c).text(c.substr(-8));
			    });
			    
			    function fill(url, id) {
				d3.json(url, function(d) {
				    d.sort()
				    d3.select(id).selectAll().data(d).enter().append('span').text(' ').append('a').attr('href', function(c){return 'share.html#' + c}).text(function(c){return c.substr(-8)});
				});
			    }
				
			    fill('/web/verified_heads', '#verified_heads');
			    fill('/web/heads', '#heads');
			    fill('/web/verified_tails', '#verified_tails');
			    fill('/web/tails', '#tails');
			    fill('../web/my_share_hashes', '#my_share_hashes');
			}
                        var plot1;
                        var plot2;
			function UpdateData()
			{
				function values(o){ res = []; for(var x in o) res.push(o[x]); return res; }

				d3.json('/local_stats', function(local_stats) {
					d3.select('#peers_in').text(local_stats.peers.incoming);
					d3.select('#peers_out').text(local_stats.peers.outgoing);
					
					var local = d3.sum(values(local_stats.miner_hash_rates));
					var local_dead = d3.sum(values(local_stats.miner_dead_hash_rates));
					d3.select('#local_rate').text(d3.format('.3s')(local) + 'H/s');
					d3.select('#local_doa').text(d3.format('.2p')(local_dead/local));
					
					d3.select('#shares_total').text(local_stats.shares.total);
					d3.select('#shares_orphan').text(local_stats.shares.orphan);
					d3.select('#shares_dead').text(local_stats.shares.dead);
					
					d3.select('#efficiency').text(local_stats.efficiency != null ? d3.format('.4p')(local_stats.efficiency) : '???')
					d3.select('#uptime_days').text(d3.format('.3f')(local_stats.uptime / 60 / 60 / 24));
					d3.select('#uptime_hours').text(d3.format('.3f')(local_stats.uptime / 60 / 60 ));
					d3.select('#block_value').text(local_stats.block_value);
					
					d3.select('#warnings').selectAll().data(local_stats.warnings).enter().append('p')
						.text(function(w){ return 'Warning: ' + w })
						.attr('style', 'color:red;border:1px solid red;padding:5px');
						
					var time_to_share = local_stats.attempts_to_share/local;
					d3.select('#time_to_share').text(d3.format('.3r')(time_to_share/3600) + " hours");
					d3.select('#time_to_share_minute').text(d3.format('.3r')(time_to_share / 60) + " ");
					
					d3.json('/global_stats', function(global_stats) {
						d3.select('#pool_rate').text(d3.format('.3s')(global_stats.pool_hash_rate) + 'H/s');
						d3.select('#pool_stale').text(d3.format('.2p')(global_stats.pool_stale_prop));
						d3.select('#difficulty').text(d3.format('.3r')(global_stats.min_difficulty));
						
						var time_to_block = local_stats.attempts_to_block/global_stats.pool_hash_rate;
						d3.select('#time_to_block').text(d3.format('.3r')(time_to_block/3600) + " hours");
						
						d3.select('#expected_payout_amount').text(d3.format('.3r')(local/global_stats.pool_hash_rate*local_stats.block_value*(1-local_stats.donation_proportion)));
										  
										  
						  /// ============================================
								var data = [
								['Local speed', local],['Local dead speed', local_dead], ['Global speed', global_stats.pool_hash_rate]
							  ];
								
                                                          if (plot2) {plot2.destroy();}
	                                                  $("#targetPlot2").remove();
	                                                  $("#SpeedChart").append("<div id='targetPlot2'></div>");
							  plot2 = jQuery.jqplot ('targetPlot2', [data],
								{ 
								  seriesDefaults: {
									// Make this a pie chart.
									renderer: jQuery.jqplot.PieRenderer, 
									rendererOptions: {
									  // Put data labels on the pie slices.
									  // By default, labels show the percentage of the slice.
									  showDataLabels: true
									}
								  }, 
								  legend: { show:true, location: 'e' }
								}
							  );
				  
					});
					
					/// ============================================
					var data = [
					['Good', local_stats.shares.total - (local_stats.shares.orphan + local_stats.shares.dead)],['Dead', local_stats.shares.dead], ['Orphaned', local_stats.shares.orphan]
				  ];
				  				
	                          if (plot1) {plot1.destroy();}
	                          $("#targetPlot1").remove();
                                  $("#ShareChart").append("<div id='targetPlot1'></div>");
	                          plot1 = jQuery.jqplot ('targetPlot1', [data],
					{ 
					  seriesDefaults: {
						// Make this a pie chart.
						renderer: jQuery.jqplot.PieRenderer, 
						rendererOptions: {
						  // Put data labels on the pie slices.
						  // By default, labels show the percentage of the slice.
						  showDataLabels: true
						}
					  }, 
					  legend: { show:true, location: 'e' }
					});
			
                    /// Active miners
                    var miners = [];
                    for (var i in local_stats.miner_hash_rates) {
                        var miner = new Object;
                        miner.miner_name=i;
                        miner.hash=local_stats.miner_hash_rates[i];
                        miners.push(miner)
                    };
                    $("#miners").html("<tr><th>Miner</th><th>Hashrate</th><th>Dead hashrate</th></tr>");
                    var tr = d3.select("#miners").selectAll().data(miners).enter().append('tr');
                    tr.append('td').text(function(miner){return miner.miner_name});
                    tr.append('td').text(function(miner){return d3.format('.3s')(miner.hash) +'H/s'});
                    tr.append('td').text(function(miner){return local_stats.miner_dead_hash_rates[miner.miner_name] != null ? d3.format('.3s')(local_stats.miner_dead_hash_rates[miner.miner_name]) + 'H/s' : '0H/s'});

                    document.title=d3.format('.3s')(local) + 'H/s (' + d3.format('.2p')(local_dead/local) + ') | ' + local_stats.shares.total + ' shares | ' + siteTitle;
				
			    });

                /// pool speed grapg
				plot_later(d3.select("#main-local"), "H/s", "H", [
                    {"url": "/web/graph_data/local_hash_rate/last_" + period, "color": "#0000FF", "label": "Total"},
                    {"url": "/web/graph_data/local_dead_hash_rate/last_" + period, "color": "#FF0000", "label": "Dead"}
                ],1000,300);

		}

		function ChangeCurrentPeriod(p_Period, p_Sender)
		{
			period=p_Period;
			UpdateData();
			$('#scale_menu li').removeClass('active');
			$('#' + p_Sender).addClass('active');
		}

		function AutoRefresh()
		{
			if($("#autorefresh").prop('checked'))
			{
				UpdateData();
			}
		}

        
                    function compose() {
                var funcs = arguments;
                return function(x) {
                    for(var i = funcs.length-1; i >= 0; i--) {
                        x = funcs[i](x);
                    }
                    return x;
                }
            }
            function itemgetter(i) { return function(x) { return x[i]; } }
            function as_date(x) { return new Date(1000*x); }
            function not_null(x) { return x != null; }
            
            function get_area_mean(data) {
                var top = 0;
                var bottom = 0;
                for(var i = 0; i < data.length; i++) {
                    if(data[i][1] == null) continue; // no data for bin
                    top += data[i][1] * data[i][2];
                    bottom += data[i][2];
                }
                return {"area": top, "mean": bottom==0?null:top/bottom};
            }
            
            function plot(g, unit, total_unit, lines,ww,hh,stack) {
                // lines is a list of objects which have attributes data, color, and label
                
                var table_div = document.createElement("div");
                g.node().parentNode.insertBefore(table_div, g.node().nextSibling);
                table_div.style.display = "none";
                

                for(var i = 0; i < lines.length; ++i) {
                    var line = lines[i];
                    var table_sel = d3.select(table_div).append('table').attr('border', 1).attr('style', 'float:left');
                    
                    var first_tr = table_sel.insert('tr');
                    first_tr.append('th').text('Date');
                    first_tr.append('th').text(line.label + '/(' + unit + ')');
                    
                    var new_data = []
                    for(var j = 0; j < line.data.length; ++j)
                        if(j % 7 == 3)
                            new_data.push(line.data[j]);
                    var tr = table_sel.selectAll().data(new_data).enter().append('tr');
                    tr.append('td').text(function(datum){return new Date(1000*datum[0]).toString()});
                    tr.append('td').text(function(datum){return d3.format(".3s")(datum[1])});
                }
                
                var margin_v = 40;
                var margin_h = 140;
                var w = ww;
		var h = hh;
                var x = d3.time.scale().domain([
                    as_date(d3.min(lines, function(line) { return d3.min(line.data, itemgetter(0)); })),
                    as_date(d3.max(lines, function(line) { return d3.max(line.data, itemgetter(0)); }))
                ]).range([0 + margin_h, w - margin_h]);
         
                
                g.attr("width", w).attr("height", h);
                g.selectAll("*").remove();
                
                if(stack) {                   
                    var data = d3.layout.stack()
                        .x(itemgetter(0))
                        .y(itemgetter(1))
                        .values(function(line){ return line.data })
                        (lines);
                    
                    var y = d3.scale.linear().domain([
                        0,
                        d3.max(data, function(d) { return d3.max(d.data, function(d) { return d.y0 + d.y; }) })
                    ]).range([h - margin_v, margin_v]);
                    
                    var y_abs = d3.scale.linear().domain([0, 1]).range([h - margin_v, margin_v]);
                    
                    g.selectAll().data(lines).enter().append("svg:path")
                        .attr("d", function(line){
                            return d3.svg.area()
                                .x(function(d) { return x(as_date(d[0])) })
                                .y0(function(d) { return y(d.y0) })
                                .y1(function(d) { return y(d.y0 + d.y) })
                                .defined(compose(not_null, itemgetter(1)))
                                (line.data)
                        })
                        .style("fill", function(line){return line.color})
                        .attr("stroke", function(line){return line.color})
                        .attr("class", "plotline");
                    
                    var total = 0;
                    var total_area = 0;
                    for(var i = 0; i < lines.length; ++i) {
                        var line = lines[i];
                        var stats = get_area_mean(line.data);
                        if(stats.mean != null) {
                            total += stats.mean;
                            total_area += stats.area;
                        }
                    }
                    
                    for(var i = 0; i < lines.length; ++i) {
                        var line = lines[i];
                        var stats = get_area_mean(line.data);
                        if(stats.mean != null) {
                            var num = 0;
                            var denom = 0;
                            for(var j = 0; j < line.data.length; j++)
                                if(line.data[j] != null) {
                                    var d = line.data[j];
                                    num += (d.y+1)*((d.y0 + d.y) + (d.y0))/2;
                                    denom += (d.y+1);
                                }
                            g.append("svg:line")
                                .style("stroke", line.color)
                                .attr("x1", w - margin_h + 3)
                                .attr("y1", y(num/denom))
                                .attr("x2", w - margin_h + 10)
                                .attr("y2", y_abs(i/lines.length));
                            g.append("svg:text")
                                .text(line.label + " (mean: " + d3.format(".3s")(stats.mean) + unit + ")")
                                .attr("text-anchor", "start")
                                .attr("dominant-baseline", "central")
                                .attr("fill", line.color)
                                .attr("x", w - margin_h + 10)
                                .attr("y", y_abs(i/lines.length));
                            if(total_unit != null)
                                g.append("svg:text")
                                    .text("Area: " + d3.format(".3s")(stats.area) + total_unit + " (" + d3.format(".2p")(stats.area/total_area) + " total)")
                                    .attr("text-anchor", "start")
                                    .attr("dominant-baseline", "central")
                                    .attr("fill", line.color)
                                    .attr("x", w - margin_h + 10)
                                    .attr("y", y_abs(i/lines.length) + 12);
                        }
                    }
                    g.append("svg:line")
                        .style("stroke", "black")
                        .attr("x1", w - margin_h + 3)
                        .attr("y1", y(total))
                        .attr("x2", w - margin_h + 10)
                        .attr("y2", y_abs(1));
                    g.append("svg:text")
                        .text("Total (mean: " + d3.format(".3s")(total) + unit + ")")
                        .attr("text-anchor", "start")
                        .attr("dominant-baseline", "central")
                        .attr("fill", "black")
                        .attr("x", w - margin_h + 10)
                        .attr("y", y_abs(1));
                    if(total_unit != null)
                        g.append("svg:text")
                            .text("Area: " + d3.format(".3s")(total_area) + total_unit)
                            .attr("text-anchor", "start")
                            .attr("dominant-baseline", "central")
                            .attr("fill", "black")
                            .attr("x", w - margin_h + 10)
                            .attr("y", y_abs(1) + 12);
                } else {
                    var y = d3.scale.linear().domain([
                        0,
                        d3.max(lines, function(line) { return d3.max(line.data, itemgetter(1)); } )
                    ]).range([h - margin_v, margin_v]);
                    
                    g.selectAll().data(lines).enter().append("svg:path")
                        .attr("d", function(line) {
                            return d3.svg.line()
                                .x(compose(x, as_date, itemgetter(0)))
                                .y(compose(y, itemgetter(1)))
                                .defined(compose(not_null, itemgetter(1)))
                                (line.data)
                        })
                        .style("stroke", function(line) { return line.color })
                        .attr("class", "plotline");
                    
                    for(var i = 0; i < lines.length; ++i) {
                        var line = lines[i];
                        var stats = get_area_mean(line.data);
                        if(stats.mean != null) {
                            g.append("svg:text")
                                .text(line.label)
                                .attr("text-anchor", "start")
                                .attr("dominant-baseline", "central")
                                .attr("fill", line.color)
                                .attr("x", w - margin_h + 10)
                                .attr("y", y(stats.mean) - 12);
                            g.append("svg:text")
                                .text("-Mean: " + d3.format(".3s")(stats.mean) + unit)
                                .attr("text-anchor", "start")
                                .attr("dominant-baseline", "central")
                                .attr("fill", line.color)
                                .attr("x", w - margin_h)
                                .attr("y", y(stats.mean));
                            if(total_unit != null)
                                g.append("svg:text")
                                    .text("Area: " + d3.format(".3s")(stats.area) + total_unit)
                                    .attr("text-anchor", "start")
                                    .attr("dominant-baseline", "central")
                                    .attr("fill", line.color)
                                    .attr("x", w - margin_h + 10)
                                    .attr("y", y(stats.mean) + 12);
                        }
                    }
                }
                
                // x axis
                
                g.append("svg:line")
                    .attr("x1", margin_h)
                    .attr("y1", h - margin_v)
                    .attr("x2", w - margin_h)
                    .attr("y2", h - margin_v);
                
                g.selectAll()
                    .data(x.ticks(13))
                    .enter().append("svg:g")
                    .attr("transform", function(d) { return "translate(" + x(d) + "," + (h-margin_v/2) + ")"; })
                    .append("svg:text")
                    .attr("transform", "rotate(45)")
                    .attr("text-anchor", "middle")
                    .attr("dominant-baseline", "central")
                    .text(x.tickFormat(13));
                
                g.selectAll()
                    .data(x.ticks(13))
                    .enter().append("svg:line")
                    .attr("x1", x)
                    .attr("y1", h - margin_v)
                    .attr("x2", x)
                    .attr("y2", h - margin_v + 5);
                
                // y axis
                
                g.append("svg:line")
                    .attr("x1", margin_h)
                    .attr("y1", h - margin_v)
                    .attr("x2", margin_h)
                    .attr("y2", margin_v);
                
                g.selectAll()
                    .data(y.ticks(6))
                    .enter().append("svg:line")
                    .attr("x1", margin_h - 5)
                    .attr("y1", y)
                    .attr("x2", margin_h)
                    .attr("y2", y);
                
                g.selectAll()
                    .data(y.ticks(6))
                    .enter().append("svg:text")
                    .text(compose(function(x) { return x + unit; }, d3.format(".2s")))
                    .attr("x", margin_h/2)
                    .attr("y", y)
                    .attr("dominant-baseline", "central")
                    .attr("text-anchor", "middle");
            }
            function plot_later(g, unit, total_unit, lines,w,h,stack) { // takes lines with url attribute instead of data attribute
                var callbacks_left = lines.length;
                lines.map(function(line) {
                    d3.json(line.url, function(line_data) {
                        line.data = line_data;
                        callbacks_left--;
                        if(callbacks_left == 0)
                            plot(g, unit, total_unit, lines,w,h,stack);
                    });
                });
            }
            
            function data_to_lines(data, sort_key) {
                var vers = {}; for(var i = 0; i < data.length; ++i) if(data[i][1] != null) for(var v in data[i][1]) if(data[i][1][v] != data[i][3]) vers[v] = null;
                var verlist = []; for(var v in vers) verlist.push(v);
                verlist.sort();
                
                lines = [];
                for(var i = 0; i < verlist.length; i++) {
                    lines.push({
                        data: data.map(function(d){ return [d[0], d[1] == null ? null : (verlist[i] in d[1] ? d[1][verlist[i]] : d[3]), d[2]] }),
                        color: d3.hsl(i/verlist.length*360, 0.5, 0.5),
                        label: verlist[i]
                    });
                }
                if(sort_key == undefined)
                    var sort_key = function(x) { return d3.max(x.data, function(d){ return d[1] }) }
                lines.sort(function(a, b){ return sort_key(a) - sort_key(b) });
                return lines;
            }
