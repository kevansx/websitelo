/*var settings = {
    MaxBallNumber: 49,
    MaxBonusBallNumber: 14,
    PickBallNumber: 6,
    BonusBallNumber: 1,
    PoolBallNumber: 1,
    selectedTicketNumbers: [],
    minTicketCount: 1,
    completedTicketCount: 0,
    url : 'https://jsonplaceholder.typicode.com/todos/20',
    tickets: [],
    stringTags : {
        showNumber : 'showNumber_',
        showBonus : 'showBonus_'
    }
};*/

function initNumberPicker(){
	//call back end update settings 
    $.ajax({
		type: "GET",
        url:settings.url,
        cache: false,
        dataType: 'json',
        success: function(data){
			console.log("request successed == ",data);
			createNumberPicker();
        },
        error: function(jqXHR, textStatus, errorThrown){
			console.log("request failed   ",textStatus);
		}
	});
}

function createNumberPicker(){
	var numberShow ='';
	var index = '';
	var i =1;
	//init ticket display number 
	for ( i = 1; i <= settings.PickBallNumber; i++){
		index = settings.stringTags.showNumber +'1_' + i;
		numberShow = '<span class="ticketNumber" id='+ index + '></span>';
		$('#choosenNumber').append(numberShow);
	}	
	//init select ticket number
	for ( i = 1; i <= settings.MaxBallNumber; i++){
		index = 'ticketNumber_1_' + i;
		numberShow = '<li class="ticketNumber" id='+ index + '  onClick="addNumber(this.id)">' + i +'</li>';
		$('#availableNumbers_1').append(numberShow);
	}
	//init bonus display number 
	for ( i = 1; i <= settings.BonusBallNumber; i++){
		index = settings.stringTags.showBonus +'1_' + i;
		numberShow = '<span class="bonusTicketNumber choosenBonus" id ='+ index + '></span>';
		$('#choosenNumber').append(numberShow);
	}	
	//init select bonus  number
	for ( i = settings.MinBonusBallNumber; i <= settings.MaxBonusBallNumber; i++){
		index = 'bonusTicketNumber_1_' + i;
		numberShow = '<li class="bonusTicketNumber" id='+ index + '  onClick="addNumber(this.id)">' + i +'</li>';
		$('#availableBonusNumbers_1').append(numberShow);
	}
	// template 
	$('#lines_1').clone().attr('id', 'template').hide().appendTo("#tickets_section");
	//init
	settings.tickets.push(1);
	if(sessionTicketNumbers != ''){
		sessionSavedTicket();
	} else {
		quickPick('#quickPick_1');
		//$("#addLine").click();
		//$("#addLine").click();
		for(i=1;i<settings.initialTicketCount;i++){
			$("#addLine").click();
		}
	}
}

function sessionSavedTicket(){
	savedTicketLength = sessionTicketNumbers.length;
	savedTicketNumbersLength = sessionTicketNumbers[0].Numbers.length;
	savedTicketBonusNumbersLength = sessionTicketNumbers[0].BonusNumbers.length;
	for(var x=0;x<savedTicketLength;x++){
		if(x > 0){
			$("#addLine").click();
		}
		var ticketNumber = x+1;
		for(var y=0;y<savedTicketNumbersLength;y++){
			addNumber('ticketNumber_'+ticketNumber+'_'+sessionTicketNumbers[x].Numbers[y]);
		}
		for(var z=0;z<savedTicketBonusNumbersLength;z++){
			addNumber('bonusTicketNumber_'+ticketNumber+'_'+sessionTicketNumbers[x].BonusNumbers[z]);
		}
	}
}

// add line function 
//$("#addLine").click(function(){  
function addLine(){
    var $boardSection = $('div[id^="lines_"]:last'); // get the last DIV where ID starts with ^= "ticket_"
    var ticketIndex = parseInt($boardSection.prop("id").match(/\d+/g), 10 ) +1; // Read the Number from that DIV's ID (i.e: 3 from "board_3") then increment that number by 1
    $('#template').clone().attr('id', 'lines_'+ ticketIndex).show().appendTo("#tickets_section");
    $('#lines_' + ticketIndex).find("#clear_1").attr("id","clear_" + ticketIndex);
    $('#lines_' + ticketIndex).find("#quickPick_1").attr("id","quickPick_" + ticketIndex);
    $('#lines_' + ticketIndex).find("#trash_1").attr("id","trash_" + ticketIndex);
    $('#lines_' + ticketIndex).find("#ticket_1").attr("id","ticket_" + ticketIndex);
    $('#lines_' + ticketIndex).find("#complete_1").attr("id","complete_" + ticketIndex);
	$('#lines_' + ticketIndex).find("#incomplete_1").attr("id","incomplete_" + ticketIndex);
    $('#lines_' + ticketIndex).find("#availableNumbers_1").attr("id","availableNumbers_" + ticketIndex);
    $('#lines_' + ticketIndex).find("#availableBonusNumbers_1").attr("id","availableBonusNumbers_" + ticketIndex);
    for(var i=1;i<=settings.PickBallNumber;i++){
        $('#lines_' + ticketIndex).find("#showNumber_" + 1 + "_" + i).attr("id","showNumber_" + ticketIndex + "_" + i);
    }
    for(var j=1;j<=settings.BonusBallNumber;j++){
        $('#lines_' + ticketIndex).find("#showBonus_" + 1 + "_" + j).attr("id","showBonus_" + ticketIndex + "_" + j);
    }
    for(var y=1;y<=settings.MaxBallNumber;y++){
        $('#lines_' + ticketIndex).find("#ticketNumber_" + 1 + "_" + y).attr("id","ticketNumber_" + ticketIndex + "_" + y);
    }
    for(var z=settings.MinBonusBallNumber;z<=settings.MaxBonusBallNumber;z++){
        $('#lines_' + ticketIndex).find("#bonusTicketNumber_" + 1 + "_" + z).attr("id","bonusTicketNumber_" + ticketIndex + "_" + z);
    }
    settings.tickets.push(ticketIndex);
    $('#addLine').appendTo('#tickets_section');
	if(sessionTicketNumbers == ''){
		quickPick('#quickPick_'+ticketIndex);
	}
	//$(".trashButton").removeClass("accountSubmitButtonInactive");
	if(settings.tickets.length == settings.minTicketCount) {
		$(".trashButton").addClass("accountSubmitButtonInactive");
	} else {
		$(".trashButton").removeClass("accountSubmitButtonInactive");
	}
	if(settings.tickets.length == settings.maxLines){
		$('#addLine').hide();
	}
//});
}

// trash function
function trashButton(e,id){
	if (!e) var e = window.event;
	e.cancelBubble = true;
	if (e.stopPropagation) e.stopPropagation();
    id = id.match(/\d+/);
    if(settings.tickets.length == settings.minTicketCount) {
		let ticketCopy = (settings.minTicketCount == 1) ? 'ticket' : 'tickets';
        alert("Please keep at least "+settings.minTicketCount+" "+ticketCopy);
        return;
    } 
    for( var j = 0; j < settings.selectedTicketNumbers.length; ++j){
        if(id == settings.selectedTicketNumbers[j].index){
            settings.selectedTicketNumbers.splice(j,1); 
        }
    }
    for(var i=0;i<settings.tickets.length;i++){
        if( parseInt(id) == settings.tickets[i]){
            settings.tickets.splice(i,1); 
        }
    }
	if($("#ticket_"+id).hasClass('ticketComplete')){
		settings.completedTicketCount--;
		getSingleTicketPrice(unitPrice,baseSingleTicketPrice);
	}
    $("#lines_"+id).remove();
	if(settings.tickets.length == settings.minTicketCount) {
		$(".trashButton").addClass("accountSubmitButtonInactive");
	}
	if(settings.tickets.length < settings.maxLines){
		$('#addLine').show();
	}
}

// clear function 
function clearButton(id){
    id = id.match(/\d+/);
	var ticketID = "ticket_"+id;
	if($("#"+ticketID).hasClass('ticketComplete')) {
		settings.completedTicketCount--;
		getSingleTicketPrice(unitPrice,baseSingleTicketPrice);
	}
    //ticketID = 1;
    for( var j = 0; j < settings.selectedTicketNumbers.length; j++){
        if(id == settings.selectedTicketNumbers[j].index){
           
            for(var k=0;k < settings.selectedTicketNumbers[j].Numbers.length; k++){
                $("#ticketNumber_"+id+"_"+settings.selectedTicketNumbers[j].Numbers[k]).removeClass("selectedNumber");
            }
            for(var l=0;l < settings.selectedTicketNumbers[j].BonusNumbers.length; l++){
                $("#bonusTicketNumber_"+id+"_"+settings.selectedTicketNumbers[j].BonusNumbers[l]).removeClass("selectedNumber");
            }
            settings.selectedTicketNumbers.splice(j,1); 
        }
    }
	$("#webUpperTicketSection #clear_"+id).addClass("accountSubmitButtonInactive");
    $("#quickPick_"+id).show();
    $("#complete_"+id).hide();
    $('#lines_' + id).find(".ticketComplete").removeClass("ticketComplete");
    $("#availableNumbers_"+id).removeClass("availableNumbersComplete");
    $("#availableBonusNumbers_"+id).removeClass("availableBonusNumbersComplete");
	showNumber(id,{},true);
}

// quick pick function 
function quickPick(id){
    var bonusNumberSelected = false;
    var numberSelected = false;
    var hasTicketMatch = false;
    var subStr = id.match("quickPick_(.*)");
    var ticket = subStr[1];
    var nums =[];
    var bonus =[];
    var i = 0;
    var index = 0;
    
    for ( i = 0; i < settings.selectedTicketNumbers.length; ++i) {
        var array = settings.selectedTicketNumbers[i];
        if(array.index == ticket){ // the ticket is already in the array
            if(array.Numbers.length == settings.PickBallNumber){
                numberSelected = true;
            }
            if(array.BonusNumbers.length == settings.BonusBallNumber) {
                bonusNumberSelected = true;
            }
            index = i;
            hasTicketMatch = true;
            break; 
        }
    }
   
    if(hasTicketMatch){
		//working on existing ticket 
		if(!numberSelected){
			nums =  new NumberPicker(settings, false).getOtherNumbers(settings.selectedTicketNumbers[index].Numbers);
			settings.selectedTicketNumbers[index].Numbers = [];
			for ( i = 0; i < nums.length; i++){
				settings.selectedTicketNumbers[index].Numbers.push(nums[i]);
			}	 
		}
		if(!bonusNumberSelected){
			bonus =  new NumberPicker(settings, true).getOtherNumbers(settings.selectedTicketNumbers[index].BonusNumbers);
			settings.selectedTicketNumbers[index].BonusNumbers = [];
			for ( i = 0; i < bonus.length; i++){
				settings.selectedTicketNumbers[index].BonusNumbers.push(bonus[i]);
			}	 
		}
		if(settings.specialFeature == 'matchBonus' && settings.completedTicketCount > 0){
			matchBonusFunction(parseInt(settings.selectedTicketNumbers[index].BonusNumbers));
		}
    } else{
        //new ticket
		nums =  new NumberPicker(settings, false).getNumbers();
		if(settings.specialFeature == 'matchBonus' && settings.selectedTicketNumbers.length > 0){
			if(settings.selectedTicketNumbers[index].BonusNumbers == ''){ // if the first ticket is incomplete (missing a bonus number)
				for(i=0;i<settings.selectedTicketNumbers.length;i++){
					if(settings.selectedTicketNumbers[i].BonusNumbers != ''){
						index = i;
						break;
					}
				}	
			}
			bonus = new NumberPicker(settings, true).getOtherNumbers(settings.selectedTicketNumbers[index].BonusNumbers);
		} else {
			bonus =  new NumberPicker(settings, true).getNumbers();
		}
		
        settings.selectedTicketNumbers.push({index:ticket,Numbers:nums,BonusNumbers:bonus});
    } 
	var index2 = '';
 
	//change selected number color  
	for ( i = 0; i < nums.length; i++){
		index2 = "ticketNumber_" + ticket + "_" + nums[i];
		$("#"+index2).addClass("selectedNumber");
	}	 

	for ( i = 0; i < bonus.length; i++){
		index2 = "bonusTicketNumber_" + ticket + "_" + bonus[i];
		$("#"+index2).addClass("selectedNumber");
	}
	$("#webUpperTicketSection #clear_"+ticket).removeClass("accountSubmitButtonInactive");
	$("#ticket_"+ticket).addClass("ticketComplete");
	$("#complete_"+ticket).show();
	settings.completedTicketCount++;
	getSingleTicketPrice(unitPrice,baseSingleTicketPrice);
	$("#quickPick_"+ticket).hide();
    var currentIndex = settings.selectedTicketNumbers.map(function (i) { return i.index; }).indexOf(ticket);
    if(settings.selectedTicketNumbers[currentIndex].Numbers.length == settings.PickBallNumber){
        $("#availableNumbers_"+ticket).addClass("availableNumbersComplete");
    } 
    if(settings.selectedTicketNumbers[currentIndex].BonusNumbers.length == settings.BonusBallNumber){
        $("#availableBonusNumbers_"+ticket).addClass("availableBonusNumbersComplete");
    }
	//if(settings.selectedTicketNumbers[currentIndex].Numbers.length == settings.PickBallNumber && settings.selectedTicketNumbers[currentIndex].BonusNumbers.length == settings.BonusBallNumber && settings.specialFeature == 'matchBonus'){
	//	matchBonusFunction(parseInt(settings.selectedTicketNumbers[currentIndex].BonusNumbers));
	//}
    showNumber(ticket,settings.selectedTicketNumbers[currentIndex],false);
}

// place bet function 	
$("#placeBetButton").click(function(e){  
    if(settings.completedTicketCount >= settings.minTicketCount){
        if(settings.tickets.length  == settings.completedTicketCount){
            //alert("successful submit");
			var ticketNumbersString = JSON.stringify(settings.selectedTicketNumbers);
			$("#jsonTicketNumbers").val(ticketNumbersString);
        } else {
			let ticketCopy = (settings.minTicketCount == 1) ? 'ticket' : 'tickets';
            var r = confirm("You have incomplete tickets. Would you like to complete them or continue with submitting your " + settings.completedTicketCount + " "+ticketCopy);
            if(r == true){
                var ticketNumberCount =0;
                var ticketBonusNumberCount =0;
				trashIncompleteTickets = new Array();
                for(x=0;x<settings.selectedTicketNumbers.length;x++){
					var getTicketIndex = settings.selectedTicketNumbers[x].index;
                    ticketNumberCount = settings.selectedTicketNumbers[x].Numbers.length;
                    ticketBonusNumberCount = settings.selectedTicketNumbers[x].BonusNumbers.length;
                    if(ticketNumberCount != settings.PickBallNumber || ticketBonusNumberCount != settings.BonusBallNumber){
						getTrashTicketIndex = "trash_"+getTicketIndex;
						trashIncompleteTickets.push(getTrashTicketIndex);
                    }
                }
				for(y=0;y<trashIncompleteTickets.length;y++){
					trashButton(event,trashIncompleteTickets[y]);
				}
				var ticketNumbersString = JSON.stringify(settings.selectedTicketNumbers);
				$("#jsonTicketNumbers").val(ticketNumbersString);
            } else {
				 e.preventDefault();
			}
        }
    } else {
		e.preventDefault();
		let ticketCopy = (settings.minTicketCount == 1) ? 'ticket' : 'tickets';
        alert("Please complete at least "+settings.minTicketCount+" "+ticketCopy);
    }
});

function addNumber(id){
	$('#resultsCheckNumberSection .secondaryFormButton').removeClass('disabledState');
    var bonusNumberSelected = false;
    var numberSelected = false;
    var hasTicketMatch = false;
    var hasTicketNumberMatch = false;
    var hasAllNumbersSelected = false;
    if(id.indexOf("bonus") != -1){
        bonusNumberSelected = true;
        var subStr = id.match("bonusTicketNumber_(.*)_(.*)");
    } else {
        numberSelected = true;
        var subStr = id.match("ticketNumber_(.*)_(.*)");
    }
    var ticket = subStr[1];
    var ticketNumber = parseInt(subStr[2]);
    var index = 0;
    for (var i = 0; i < settings.selectedTicketNumbers.length; ++i) {
        var array = settings.selectedTicketNumbers[i];
        if(array.index == ticket){ // the ticket is already in the array
            if(numberSelected == true){
                for (var y = 0; y < array.Numbers.length; ++y) {
                    var array2 = array.Numbers[y];
                    if(array2 == ticketNumber){
                        settings.selectedTicketNumbers[i].Numbers.splice( $.inArray(ticketNumber,settings.selectedTicketNumbers[i].Numbers) ,1 );
                        if(array.Numbers.length != settings.PickBallNumber){
                            $("#availableNumbers_"+ticket).removeClass("availableNumbersComplete");
                        }
                        hasTicketNumberMatch = true;
                        hasAllNumbersSelected = false;
                    } else if(array.Numbers.length == settings.PickBallNumber){
                        hasAllNumbersSelected = true;
                    }
                }
            } else if(bonusNumberSelected == true) {
                for (var y = 0; y < array.BonusNumbers.length; ++y) {
                    var array2 = array.BonusNumbers[y];
                    if(array2 == ticketNumber){
                        settings.selectedTicketNumbers[i].BonusNumbers.splice( $.inArray(ticketNumber,settings.selectedTicketNumbers[i].BonusNumbers) ,1 );
                        if(array.BonusNumbers.length != settings.BonusBallNumber){
                            $("#availableBonusNumbers_"+ticket).removeClass("availableBonusNumbersComplete");
                        }
                        hasTicketNumberMatch = true;
                        hasAllNumbersSelected = false;
                    } else if(array.BonusNumbers.length == settings.BonusBallNumber){
                        hasAllNumbersSelected = true;
                    }
                }
            }
            index = i;
            hasTicketMatch = true;
            break; 
        }
    }
    
    if(hasTicketMatch == false){
        //new ticket 
        if(numberSelected == true){
            settings.selectedTicketNumbers.push({index:ticket,Numbers:[ticketNumber],BonusNumbers:[]});
        } else if(bonusNumberSelected == true){
            settings.selectedTicketNumbers.push({index:ticket,Numbers:[],BonusNumbers:[ticketNumber]});
        }
    } else if(hasTicketMatch == true && hasTicketNumberMatch == false && hasAllNumbersSelected == false) {
        //working on existing ticket 
        if(numberSelected == true){
            settings.selectedTicketNumbers[index].Numbers.push(ticketNumber);
        } else if(bonusNumberSelected == true){
            settings.selectedTicketNumbers[index].BonusNumbers.push(ticketNumber);
			//if(settings.specialFeature == 'matchBonus' && settings.selectedTicketNumbers.length > 0){
			//	matchBonusFunction(ticketNumber);
			//}
        }
    } 
            
    if(hasTicketNumberMatch == false && hasAllNumbersSelected == false){
        $("#"+id).addClass("selectedNumber");
    } else {
        $("#"+id).removeClass("selectedNumber");
    }
    if(hasTicketMatch == true && settings.selectedTicketNumbers[index].Numbers.length == settings.PickBallNumber && settings.selectedTicketNumbers[index].BonusNumbers.length == settings.BonusBallNumber){
		if(!($("#ticket_"+ticket).hasClass("ticketComplete"))){
        $("#ticket_"+ticket).addClass("ticketComplete");
		$('#resultsCheckNumberSection .primaryFormButton').removeClass('disabledState');
		$("#webUpperTicketSection #clear_"+ticket).removeClass("accountSubmitButtonInactive");
        $("#complete_"+ticket).show();
        settings.completedTicketCount++;
        $("#quickPick_"+ticket).hide();
		getSingleTicketPrice(unitPrice,baseSingleTicketPrice); // hid this when working on results number pick. This was throwing error. But I dont think it's actually being used in the Lottery Pages???
		}
    } else {
		if($('#ticket_' + ticket).hasClass("ticketComplete")){
			settings.completedTicketCount--;
			getSingleTicketPrice(unitPrice,baseSingleTicketPrice); // hid this when working on results number pick. This was throwing error. But I dont think it's actually being used in the Lottery Pages???
		}
        $('#lines_' + ticket).find(".ticketComplete").removeClass("ticketComplete");
		$('#resultsCheckNumberSection .primaryFormButton').addClass('disabledState');
        $("#complete_"+ticket).hide();
        $("#quickPick_"+ticket).show();
    }
    settings.selectedTicketNumbers[index].Numbers.sort(function(a, b) { return a - b; });
    settings.selectedTicketNumbers[index].BonusNumbers.sort(function(a, b) { return a - b; });
    var currentIndex = settings.selectedTicketNumbers.map(function (i) { return i.index; }).indexOf(ticket);
    if(settings.selectedTicketNumbers[currentIndex].Numbers.length == settings.PickBallNumber){
        $("#availableNumbers_"+ticket).addClass("availableNumbersComplete");
    } 
    if(settings.selectedTicketNumbers[currentIndex].BonusNumbers.length == settings.BonusBallNumber){
        $("#availableBonusNumbers_"+ticket).addClass("availableBonusNumbersComplete");
    }
	if(settings.selectedTicketNumbers[currentIndex].Numbers.length == settings.PickBallNumber && settings.selectedTicketNumbers[currentIndex].BonusNumbers.length == settings.BonusBallNumber && settings.specialFeature == 'matchBonus'){
		matchBonusFunction(parseInt(settings.selectedTicketNumbers[currentIndex].BonusNumbers));
	}
    showNumber(ticket,settings.selectedTicketNumbers[currentIndex],false);
}

function showNumber(id,selectedNumbers,reset){
    //show ticket number 
    for (var i = 0; i < settings.PickBallNumber; i++)
    {
        var index = 1 + i;
        var span = document.getElementById(settings.stringTags.showNumber +id+"_"+index);
        if (span)
        {  
           span.innerHTML = '';
           if(reset){
            span.innerHTML = ''; // clear existing
           }else{
            span.innerHTML = (selectedNumbers.Numbers[i] != undefined) ? selectedNumbers.Numbers[i]:''; 
           }
          
        }
    }	
     //show bonus  number 
    for (var j = 0; j < settings.BonusBallNumber; j++)
    {
        var index2 = 1 + j;
        var span2 = document.getElementById(settings.stringTags.showBonus +  +id+"_"+index2);
        if (span2)
        {
            span2.innerHTML = ''; // clear existing
           if(reset){
            span2.innerHTML = ''; // clear existing
           }else{
           span2.innerHTML = (selectedNumbers.BonusNumbers[j] != undefined) ?selectedNumbers.BonusNumbers[j]:''; 
           }
        }
    }	
  }
  
  
/*-------------------------  ANGIE ADDED THIS  -------------------------*/

function showTicket(id){
	var $window = $(window);
	var windowsize = $window.width();
	if(windowsize < 768){
		if($("#mobileTicketWindow").is(":hidden")){
			$(window).scrollTop(0);
		}
		if($("#"+id).find('.selectedNumber').length !== 0){ 
			$(".clearButton").removeClass("unclickableButton");
			$(".done").removeClass("unclickableButton");
		} else {
			$(".clearButton").addClass("unclickableButton");
			$(".done").addClass("unclickableButton");
		}
		ticketNumber = id.split('_').pop();
		ticketNumber = parseInt(ticketNumber);
		indexOfCurrentTicket = (settings.tickets).indexOf(ticketNumber) + 1;
		$("#mobileCurrentTicket").text("Line "+indexOfCurrentTicket+" of "+settings.tickets.length);
		$('div[id^="lines_"]').each(function(i,el){
			tickets = $(this).attr('id');
			//$('#'+tickets).css("height","0");
			//$('#'+tickets+' .lines').css({"height":"0","margin":"0","border-size":"0"});
			$('#'+tickets).hide();
		});
		//$("#"+id).show();
		//$('#'+id).css("height","auto");
		$('#'+id).show();
		$("#"+id).addClass("showTicket");
		$("#main").css("position","absolute");
		$("#mobileTicketWindow").show();
		$(".navbar-default,.verificationBanner,#lotteryTabs,.banner,#cookie-prompt,.howToPlay").hide();
		$(".lotteryBanners,#lotteryHeaders,.ticketSectionFeatures").hide();
		$("#singleSyndicateTabs").hide();
		$("#tickets_section").addClass("mobileLinesSection");
		$("#addLine").hide();
		$(".singleOrderDetails,.lotteryDetails,footer").hide();
		$("#mobileViewTickets").show();
		$(".quickPickButton").show();
		$("#placeBetButton").hide();
		if(indexOfCurrentTicket == settings.tickets.length){
			$("#nextLine").addClass("unclickableButton");
		} else {
			$("#nextLine").removeClass("unclickableButton");
		}
		if(indexOfCurrentTicket == 1 || settings.tickets.length == 1){
			$("#prevLine").addClass("unclickableButton");
		} else {
			$("#prevLine").removeClass("unclickableButton");
		}
		finishedTicketStyling(id);
	}
}
			
function closeTicketWindow(e){
	if (!e) var e = window.event;
	e.cancelBubble = true;
	if (e.stopPropagation) e.stopPropagation();
	var thisTicketWindow = $(".showTicket").attr('id');
	$('div[id^="lines_"]').each(function(i,el){
		tickets = $(this).attr('id');
		//$('#'+tickets+' .lines').css({"height":"61px","margin":"0 0 15px 0","border-size":"2px"});
		$('#'+tickets).show();
	});
	$("#"+thisTicketWindow).removeClass("showTicket");
	$("#main").css("position","relative");
	$(".singleOrderDetails,.lotteryDetails,footer,#lotteryHeaders,.ticketSectionFeatures,.howToPlay").show();
	$("#mobileTicketWindow").hide();
	$("#mobileViewTickets").hide();
	$(".quickPickButton").hide();
	//if(settings.tickets.length < settings.maxLines){
	if((typeof settings.maxLines === 'undefined') || (settings.tickets.length < settings.maxLines)){
		$("#addLine").show();
	}
	$("#placeBetButton").show();
	$(".navbar-default,.verificationBanner,#lotteryTabs,.banner,#cookie-prompt").show();
	$(".lotteryBanners").show();
	$("#singleSyndicateTabs").show();
	$("#tickets_section").removeClass("mobileLinesSection");
}
	
function viewPrevTicket(){
	var ticketArray = new Array();
	$('div[id^="lines_"]').each(function(i,el){
		if($(this).attr('id').match(/\d+/g) !== null){
			ticketArray.push($(this).attr('id'));
		}
	});
	var thisTicketWindow = $(".showTicket").attr('id');
	var indexOfCurrentTicket = (ticketArray).indexOf(thisTicketWindow);
	if(indexOfCurrentTicket !== 0){
		var prevTicket = indexOfCurrentTicket - 1;
		var prevTicketId = ticketArray[prevTicket];
		$("#"+thisTicketWindow).removeClass("showTicket");
		showTicket(prevTicketId);
	}
}
	
function viewNextTicket(){
	var ticketArray = new Array();
	$('div[id^="lines_"]').each(function(i,el){
		if($(this).attr('id').match(/\d+/g) !== null){
			ticketArray.push($(this).attr('id'));
		}
	});
	var thisTicketWindow = $(".showTicket").attr('id');
	var indexOfCurrentTicket = (ticketArray).indexOf(thisTicketWindow);
	if(indexOfCurrentTicket !== (ticketArray.length - 1)){
		var nextTicket = indexOfCurrentTicket + 1;
		var nextTicketId = ticketArray[nextTicket];
		$("#"+thisTicketWindow).removeClass("showTicket");
		showTicket(nextTicketId);
	}
}
	
function finishedTicketStyling(id){
	if($("#"+id).find('.ticketComplete').length !== 0){ // change the background color of tickets that are complete
		$("#mobileTicketWindow").addClass("mobileTicketWindowComplete");
	} else {
		$("#mobileTicketWindow").removeClass("mobileTicketWindowComplete");
	}
}

if (window.location.href.indexOf("single") > -1) {
	$(".singleBet").addClass("singleSyndicateTabActive");
	$(".syndicateBet").removeClass("singleSyndicateTabActive");
} else if (window.location.href.indexOf("syndicate") > -1) {
	$(".syndicateBet").addClass("singleSyndicateTabActive");
	$(".singleBet").removeClass("singleSyndicateTabActive");
}

$("#clearAll").on('click', function(){
	completedTickets = new Array();
	for( var j = 0; j < settings.selectedTicketNumbers.length; ++j){
		completedTickets.push(settings.selectedTicketNumbers[j].index); 
	}
	for(var k=0;k<completedTickets.length;k++){
		clearButton("clear_"+completedTickets[k]); 
	}
});
	
$("#quickPickAll").on('click', function(){
	completedTickets = new Array();
	for( var j = 0; j < settings.selectedTicketNumbers.length; ++j){
		completedTickets.push(parseInt(settings.selectedTicketNumbers[j].index)); 
	}
	for( var j = 0; j < settings.tickets.length; ++j){
		if(!(completedTickets.includes(settings.tickets[j]))){
			quickPick("quickPick_"+settings.tickets[j]); 
		}
	}
});
	
// START: WAS IN EACH LOTTERY PAGE... MOVING IT HERE
function isWhole(n) {
	return /^\d+$/.test(n);
}

$("#weekCount").focusout(function(){ // get the share count when customer manually enters share amount
	getWeekValue = $(".lotteryCount span input").val();
	if(getWeekValue <= 1){
		$(".lotteryCount span input").val(1);
		$(".lotteryCountMinus").addClass('fadeoutCounter');
		$(".drawDateStarting").hide();
	} else if(getWeekValue > 16){
		$(".lotteryCount span input").val(16);
		$(".lotteryCountPlus").addClass('fadeoutCounter');
		$(".lotteryCountMinus").removeClass('fadeoutCounter');
		$(".drawDateStarting").show();
	} else if(!(isWhole(getWeekValue))) { // check if user entered a whole number
		$(".lotteryCount span input").val(1);
		$(".lotteryCountMinus").addClass('fadeoutCounter');
		$(".drawDateStarting").hide();
	} else {
		$(".lotteryCountMinus").removeClass('fadeoutCounter');
		$(".drawDateStarting").show();
	}
	getSingleTicketPrice(unitPrice,baseSingleTicketPrice);
});


$("#lottoDrawDays input[type='checkbox']").on('click', function(){
	var checkboxCount = $('#lottoDrawDays').find('input[type=checkbox]:checked').length;
	if(checkboxCount == 0){
		return false;
	} else {
		getSingleTicketPrice(unitPrice,baseSingleTicketPrice);
	}
});

$(".subscriptionCheckbox[type='checkbox']").on('click', function(){
	if($(this).is(":checked")){
		$("#billingPeriodOrDuration").html("Pick Billing Cycle");
		$("#placeBetButton,#placePromoButton").html("Subscribe");
		$("#subscriptionEveryWeekCopy,.drawDateStarting").show();
		$(".lotteryCounter p.lotteryCount input").css("margin-top","1px");
	} else {
		$("#billingPeriodOrDuration").html("Duration");
		$("#placeBetButton,#placePromoButton").html("Play Now");
		$("#subscriptionEveryWeekCopy").hide();
		if($('#weekCount').val() == 1){
			$(".drawDateStarting").hide();
		}
		$(".lotteryCounter p.lotteryCount input").css("margin-top","9px");
	}
});

$(".lotteryCountPlus").on('click', function () {
	let inputValue = $('input[name="singlePlayWeeks"]').val();
	inputValue++;
	if(inputValue > 1){
		var removeStyle = $(".lotteryCountMinus").removeClass('fadeoutCounter');
		$(".drawDateStarting").show();
	}
	
	if(inputValue > 15){
		$(".lotteryCountPlus").addClass('fadeoutCounter');
	}
	
	$('input[name="singlePlayWeeks"]').val(inputValue);
	getSingleTicketPrice(unitPrice,baseSingleTicketPrice);
});

$(".lotteryCountMinus").on('click', function () {
	let inputValue = $('input[name="singlePlayWeeks"]').val();	
	if(inputValue != 1){
		inputValue--;
		if(inputValue == 1){
			$(".drawDateStarting").hide();
			$(this).addClass('fadeoutCounter');
		}
	}
	
	if(inputValue < 16){
		$(".lotteryCountPlus").removeClass('fadeoutCounter');
	}
	
	$('input[name="singlePlayWeeks"]').val(inputValue);
	getSingleTicketPrice(unitPrice,baseSingleTicketPrice);
});

$(".lotteryCount").on('click', function (){
	event.stopPropagation();
});

$(".betButtonError").on("click", function(){
	$("#fatalErrorMessage,#overlay").show();
});
/* // loaded in react now
var drawCountdown = $("#drawCounter span").html();
if(Date.parse(drawCountdown)){
	var x = setInterval(function() {
		nextDrawDateCounterdown = getBannerCounterdown(drawCountdown);
		$("#drawCounter span").html(nextDrawDateCounterdown).show();
	}, 1000);
} else {
	$("#drawCounter span").html("To be announced").show();
}

$('.drawDateCountdown').each(function(i, obj) {
	var date = $(obj).html();
	var x = setInterval(function() {
		$(obj).show();
		if($(obj).hasClass('drawDateCountdownCopy')){
			$(obj).html(getDrawDatesCounterdown(date));
		}
	}, 1000);
});
*/
function getSingleTicketPrice(singleTicketPrice,baseSingleTicketPrice){
	var countWeeks = $("#weekCount").val();
	var week = (countWeeks > 1) ? 'Weeks' :'Week';
	$("#subscriptionWeekCopy").html(week);
	var countCompletedLines = settings.completedTicketCount;
	var countDrawDaysChecked = $('#lottoDrawDays').find('input[type=checkbox]:checked').length;
	var line = (countCompletedLines > 1 || countCompletedLines == 0) ? 'lines' :'line'; 
	var betCount = countWeeks * countDrawDaysChecked;
	var draw = (betCount > 1 || betCount == 0) ? 'draws' :'draw';
	
	if(baseSingleTicketPrice == null){
		$(".linesDrawsAmount").html((((singleTicketPrice * countCompletedLines) * countDrawDaysChecked) * countWeeks).toFixed(2));
	} else {
		var drawAmountBeforeBonus = (((baseSingleTicketPrice * countCompletedLines) * countDrawDaysChecked) * countWeeks);
		var drawAmount = (((singleTicketPrice * countCompletedLines) * countDrawDaysChecked) * countWeeks);
		$(".linesDrawsAmount").html((drawAmountBeforeBonus).toFixed(2));
		$(".linesDrawsTotalAmount").html((drawAmount).toFixed(2));
	}

	if($(".subscriptionCheckbox[type='checkbox']").is(":checked")){
		$("#linesDrawsCount").html(countCompletedLines + " " + line + " x " + betCount + " " + draw + " (" + countWeeks + " week billing cycle)");
	} else {
		$("#linesDrawsCount").html(countCompletedLines + " " + line + " x " + betCount + " " + draw);
	}
	
}

function matchBonusFunction(bonus){
	for(i=0;i<settings.selectedTicketNumbers.length;i++){
		let oldBonus = settings.selectedTicketNumbers[i].BonusNumbers;
		let value = settings.selectedTicketNumbers[i].index;
		removeBonusStyle(value,oldBonus);
	}
	for(i=0;i<settings.selectedTicketNumbers.length;i++){
		let newBonus = bonus;
		let value = settings.selectedTicketNumbers[i].index;
		settings.selectedTicketNumbers[i].BonusNumbers.splice( $.inArray(value,settings.selectedTicketNumbers[i].BonusNumbers) ,1 );
		settings.selectedTicketNumbers[i].BonusNumbers.push(newBonus);
		$("#bonusTicketNumber_"+value+"_"+newBonus).addClass("selectedNumber");
		$('#lines_'+value+' #choosenNumber .bonusTicketNumber').html(newBonus);
	}
}

function removeBonusStyle(value,oldBonus){
	$("#bonusTicketNumber_"+value+"_"+oldBonus).removeClass("selectedNumber");
}
// END: WAS IN EACH LOTTERY PAGE... MOVING IT HERE