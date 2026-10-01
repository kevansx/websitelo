'use strict';

class Clock extends React.Component{
	constructor(props){
		super(props);
		this.state = {date: new Date()};
	}
	
	componentDidMount(){
		this.timerID = setInterval(
			() => this.tick(),
			1000
		);
	}
	
	componentWillUnmount(){
		clearInterval(this.timerID);
	}
	
	tick(){
		this.setState({
			date: new Date()
		});
	}
	
	render(){
		return(
			<span>Current Time: {this.state.date.toLocaleTimeString([],{ hour: '2-digit', minute: '2-digit' })}</span>
		);
	}
}

let currentReactTime = document.getElementById('currentReactTime');
if(currentReactTime){
	ReactDOM.render(
		<Clock />,
		currentReactTime
	);
}

//-------------------

class PHPToReactCounter extends React.Component {
    constructor(props) {
        super(props);
		this.state = {date: ''};
    }
	
	componentDidMount(){
		this.timerID = setInterval(
			() => this.tick(),
			1000
		);
	}
	
	componentWillUnmount(){
		clearInterval(this.timerID);
	}
	
	tick(){
		let daycounter = new Date(this.props.drawdate).getTime() - new Date().getTime() ;
		this.setState({
			date: daycounter
		});
	}
  
	render(){
		let countdownTimer = <CountdownToTime countdown={new Date(this.props.drawdate).getTime() - new Date().getTime()} drawdateshort={this.props.drawdateshort} />;
		return(
			<span>
				{countdownTimer}
			</span>
		)
	}
}

function CountdownToTime(props){
	const countdown = props.countdown;
	const drawDay = props.drawdateshort;
	if((!isNaN(countdown)) && (countdown >= 0)){
		var days = Math.floor(countdown / (1000 * 60 * 60 * 24));
		var hours = Math.floor((countdown % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
		var minutes = Math.floor((countdown % (1000 * 60 * 60)) / (1000 * 60));
		var seconds = Math.floor((countdown % (1000 * 60)) / 1000);
		let counter;
		if(drawDay == 1){
			if(days > 1){
				counter = days+" days";
			} else if(days == 1){
				counter = days+" day";
			} else {
				counter = hours+":"+(minutes>10?"":"0")+minutes+":"+(seconds>10?"":"0")+seconds;
			}
		} else {
			counter = days+" Day(s) "+hours+":"+(minutes<10?'0':'')+minutes+":"+(seconds < 10 ? '0':'') + seconds;
		}
		return counter;
	}
	return "To Be Announced";
}

// Only mount the React counter on elements that actually provide a
// data-drawdate. Elements without it (e.g. server-rendered `.wl-countdown`
// spans ticked by the global countdown in base.html) must be left alone,
// otherwise React clobbers them with "To Be Announced".
let dates = document.getElementsByClassName("lottoTicketCounter");
for(var i = 0; i < dates.length; i++){
	let dateEl = dates[i];
	if(!dateEl || !dateEl.dataset || !dateEl.dataset.drawdate) continue;
	ReactDOM.render(
		<PHPToReactCounter {...dateEl.dataset} />,
		dateEl
	);
}

let lottoBannerDate = document.getElementById("drawCounterReact");
if(lottoBannerDate && lottoBannerDate.dataset && lottoBannerDate.dataset.drawdate){
	ReactDOM.render(
		<PHPToReactCounter {...lottoBannerDate.dataset} />,
		lottoBannerDate
	);
}

let lottoCheckboxDates = document.getElementsByClassName("drawDateCountdownReact");
for(var i = 0; i < lottoCheckboxDates.length; i++){
	let checkboxEl = lottoCheckboxDates[i];
	if(!checkboxEl || !checkboxEl.dataset || !checkboxEl.dataset.drawdate) continue;
	ReactDOM.render(
		<PHPToReactCounter {...checkboxEl.dataset} />,
		checkboxEl
	);
}

//----------------------------

class PHPToReactTimeOnSite extends React.Component{
	constructor(props) {
        super(props);
		this.state = {date: parseInt(this.props.drawdate, 10) || 0};
    }
	
	componentDidMount(){
		this.timerID = setInterval(
			() => this.tick(),
			1000
		);
	}
	
	componentWillUnmount(){
		clearInterval(this.timerID);
	}
	
	tick(){
		this.setState(state => ({
			date: state.date + 1
		}));
	}
  
	render(){
		let countdownTimer = <FormatTimeOnSite countdown={this.state.date} />;
		return(
			<span>
				Current Session: {countdownTimer}
			</span>
		)
	}
}

function FormatTimeOnSite(props) {
	let countdown = props.countdown;
	let hours   = Math.floor(countdown / 3600);
    let minutes = Math.floor(countdown / 60) % 60;
    let seconds = countdown % 60;
    return [hours, minutes, seconds]
        .map(v => ('' + v).padStart(2, '0')) // (''+v) puts a space in front of v so that you can add a 0 in the first position with padStart ('5' would become ' 5' and padStart add a 0 in the empty space)
        //.filter((v,i) => v !== '00' || i > 0)
        .join(':');
}

let timeOnsite = document.getElementById("timeOnSiteCounter");
if(timeOnsite){
	ReactDOM.render(
		<PHPToReactTimeOnSite {...timeOnsite.dataset} />,
		document.getElementById('displayTimeOnSite')
	);
	ReactDOM.render(
		<PHPToReactTimeOnSite {...timeOnsite.dataset} />,
		document.getElementById('displayTimeOnSiteM')
	);
}
